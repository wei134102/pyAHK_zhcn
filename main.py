import sys, re, subprocess, tempfile, shutil, textwrap
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QListWidget, QListWidgetItem, QTextEdit,
    QFileDialog, QMessageBox, QGridLayout, QDialog, QCheckBox,
    QInputDialog, QMenu, QLabel, QFrame, QSizePolicy
)

# ───────── constants ─────────
MODS = {"ctrl":"^", "alt":"!", "shift":"+", "win":"#"}
SPECIALS = {
    "enter","return","tab","esc","escape","space","backspace","bs",
    "delete","del","home","end","pgup","pgdn","up","down","left","right"
}
CLICK_TRIGGERS = {
    "click":"LButton","left click":"LButton","click left":"LButton",
    "click right":"RButton","right click":"RButton"
}

# ───────── helpers ─────────
def to_ahk_step(token: str) -> str:
    t = token.strip()
    if m := re.fullmatch(r"(?i)click\s+x(\d+)", t):
        return f"Click {int(m.group(1))}"
    if t.lower().startswith("click"):
        return t
    if m := re.fullmatch(r"(\d+(?:\.\d+)?)\s*s", t, re.I):
        return f"Sleep {int(float(m.group(1))*1000)}"
    if t.startswith('"') and t.endswith('"'):
        return f"Send {t}"
    parts = re.split(r"[+\-\s]+", t)
    mods = "".join(MODS.get(p.lower(), "") for p in parts[:-1])
    raw = parts[-1]
    key = raw.lower() if len(raw)==1 and raw.isalnum() else raw
    if not (len(key)==1 and key.isalnum()):
        key = f"{{{key}}}"
    return f'Send "{mods}{key}"'

def hotkey_to_ahk(raw: str) -> str:
    r = raw.strip().lower()
    if r in CLICK_TRIGGERS:
        return CLICK_TRIGGERS[r]
    return "".join(
        MODS.get(t.lower(), t.lower())
        for t in re.split(r"[+\-\s]+", raw.strip())
    )

# ───────── small key‐picker ─────────
class KeyPicker(QDialog):
    KEYS = (
        list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        + [str(i) for i in range(10)]
        + ["+", "-", ".", "/"]
        + ["Enter","Tab","Esc","Space","Backspace","Delete",
           "Up","Down","Left","Right","Home","End","PgUp","PgDn","Pause"]
        + ["Numpad0","Numpad1","Numpad2","Numpad3","Numpad4",
           "Numpad5","Numpad6","Numpad7","Numpad8","Numpad9",
           "NumpadDot","NumpadAdd","NumpadSub","NumpadMult",
           "NumpadDiv","NumpadEnter"]
    )
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pick key or click")
        self.result = ""
        lay = QVBoxLayout(self)

        modrow = QHBoxLayout()
        self.c = QCheckBox("Ctrl"); self.a = QCheckBox("Alt")
        self.s = QCheckBox("Shift"); self.w = QCheckBox("Win")
        for chk in (self.c,self.a,self.s,self.w):
            modrow.addWidget(chk)
        for label,cmd in [
            ("Click","Click"),
            ("Click x2","Click x2"),
            ("Click x3","Click x3"),
            ("RClick","Click right")
        ]:
            b = QPushButton(label)
            b.setFixedWidth(60)
            b.setToolTip(f"Add {cmd} action")
            b.clicked.connect(lambda _, k=cmd: self._picked(k))
            modrow.addWidget(b)
        lay.addLayout(modrow)

        normal_keys = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ") + [str(i) for i in range(10)] \
            + ["+","-",".","/","Enter","Tab","Esc","Space","Backspace","Delete",
               "Up","Down","Left","Right","Home","End","PgUp","PgDn","Pause"]
        numpad_keys = ["Numpad0","Numpad1","Numpad2","Numpad3","Numpad4",
                       "Numpad5","Numpad6","Numpad7","Numpad8","Numpad9",
                       "NumpadDot","NumpadAdd","NumpadSub","NumpadMult",
                       "NumpadDiv","NumpadEnter"]

        grid = QGridLayout()
        main_label = QLabel("Main")
        main_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(main_label,0,0,1,10)
        row,col = 1,0
        for k in normal_keys:
            btn=QPushButton(k); btn.setFixedWidth(44)
            btn.clicked.connect(lambda _, kk=k: self._picked(kk))
            grid.addWidget(btn,row,col)
            col+=1
            if col==10: col=0; row+=1

        row+=1
        label=QLabel("NumPad")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(label,row,0,1,10)
        row+=1; col=0
        DISPLAY={"NumpadAdd":"+","NumpadSub":"-","NumpadMult":"*",
                 "NumpadDiv":"/","NumpadDot":".","NumpadEnter":"Enter"}
        for k in numpad_keys:
            face=DISPLAY.get(k,k.replace("Numpad",""))
            btn=QPushButton(face); btn.setFixedWidth(44)
            btn.clicked.connect(lambda _, kk=k: self._picked(kk))
            grid.addWidget(btn,row,col)
            col+=1
            if col==10: col=0; row+=1

        lay.addLayout(grid)

    def _picked(self,key):
        if key.lower().startswith("click"):
            self.result = key
        else:
            mods=[m for m,chk in
                  (("Ctrl",self.c),("Alt",self.a),
                   ("Shift",self.s),("Win",self.w))
                  if chk.isChecked()]
            self.result = "+".join(mods+[key]) if mods else key
        self.accept()

# ───────── main window ─────────
class KeyMapper(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("pyAHK")
        self.maps = []
        self.control_items = {}

        root=QWidget(); self.setCentralWidget(root)
        V=QVBoxLayout(root)

        # Trigger hot-key
        self.trigger=QLineEdit()
        self.trigger.setReadOnly(True)
        self.trigger.setPlaceholderText("Choose hotkey to map on")
        btn_t=QPushButton("⌨"); btn_t.setFixedWidth(28)
        btn_t.setToolTip("Choose hotkey to map on")
        btn_t.clicked.connect(lambda: self._pick_into(self.trigger))
        old_tp=self.trigger.mousePressEvent
        def triggerClicked(ev):
            self._pick_into(self.trigger); old_tp(ev)
        self.trigger.mousePressEvent=triggerClicked
        row=QHBoxLayout()
        row.addWidget(self.trigger); row.addWidget(btn_t)
        V.addLayout(row)

        # Sequence builder
        seqrow=QHBoxLayout()
        self.seq=QListWidget()
        self.seq.setMaximumHeight(120)
        self.seq.setToolTip("Mapping Functions")
        self.seq.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.seq.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.seq.customContextMenuRequested.connect(self._seq_context_menu)
        col=QVBoxLayout()
        for lab,fn,tip in [
            ("⌨",self._add_key,"Add keystroke"),
            ("⏱",self._add_delay,"Add delay"),
            ("🖉",self._add_text,"Add text")
        ]:
            b=QPushButton(lab); b.setFixedWidth(28)
            b.setToolTip(tip); b.clicked.connect(fn)
            col.addWidget(b)
        seqrow.addWidget(self.seq); seqrow.addLayout(col)
        V.addLayout(seqrow)

        # Toggle + Exit + Info row
        te_row=QHBoxLayout()
        self.toggle=QLineEdit(); self.toggle.setPlaceholderText("Toggle hot-key")
        self.toggle.setToolTip("Hotkey to pause/resume script")
        btn_toggle=QPushButton("⌨"); btn_toggle.setFixedWidth(28)
        btn_toggle.setToolTip("Pick toggle hotkey")
        btn_toggle.clicked.connect(lambda: self._pick_into(self.toggle))
        old_to=self.toggle.mousePressEvent
        def toggleClicked(ev):
            self._pick_into(self.toggle); old_to(ev)
        self.toggle.mousePressEvent=toggleClicked

        self.exit=QLineEdit(); self.exit.setPlaceholderText("Exit hot-key")
        self.exit.setToolTip("Hotkey to exit script")
        btn_exit=QPushButton("⌨"); btn_exit.setFixedWidth(28)
        btn_exit.setToolTip("Pick exit hotkey")
        btn_exit.clicked.connect(lambda: self._pick_into(self.exit))
        old_ex=self.exit.mousePressEvent
        def exitClicked(ev):
            self._pick_into(self.exit); old_ex(ev)
        self.exit.mousePressEvent=exitClicked

        self.info=QLineEdit(); self.info.setPlaceholderText("Info hot-key")
        self.info.setToolTip("Hotkey to show current mappings")
        btn_info=QPushButton("⌨"); btn_info.setFixedWidth(28)
        btn_info.setToolTip("Pick info hotkey")
        btn_info.clicked.connect(lambda: self._pick_into(self.info))
        old_if=self.info.mousePressEvent
        def infoClicked(ev):
            self._pick_into(self.info); old_if(ev)
        self.info.mousePressEvent=infoClicked

        te_row.addWidget(self.toggle); te_row.addWidget(btn_toggle)
        te_row.addSpacing(10)
        te_row.addWidget(self.exit);  te_row.addWidget(btn_exit)
        te_row.addSpacing(10)
        te_row.addWidget(self.info);  te_row.addWidget(btn_info)
        V.addLayout(te_row)

        # Add / Reset
        add=QPushButton("Add mapping",clicked=self.add_mapping)
        add.setFixedWidth(100)
        reset=QPushButton("Reset",clicked=self._reset_all)
        reset.setFixedWidth(100)
        left_ctrl=QHBoxLayout()
        left_ctrl.addStretch(); left_ctrl.addWidget(add); left_ctrl.addStretch()
        right_ctrl=QHBoxLayout()
        right_ctrl.addStretch(); right_ctrl.addWidget(reset); right_ctrl.addStretch()
        ctrl=QHBoxLayout()
        ctrl.addLayout(left_ctrl,1); ctrl.addLayout(right_ctrl,1)
        V.addLayout(ctrl)

        V.addSpacing(8)
        sep=QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background:grey;"); sep.setFixedHeight(2)
        V.addWidget(sep)

        # Mappings & Preview
        mapping_label=QLabel("Key Mappings")
        mapping_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_label=QLabel("AutoHotKey Script")
        preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.maplist=QListWidget()
        self.maplist.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.maplist.customContextMenuRequested.connect(self._maplist_context_menu)

        self.preview=QTextEdit(); self.preview.setReadOnly(True)

        left=QVBoxLayout(); left.addWidget(mapping_label); left.addWidget(self.maplist)
        right=QVBoxLayout(); right.addWidget(preview_label); right.addWidget(self.preview)
        disp=QHBoxLayout(); disp.setStretch(0,1); disp.setStretch(1,1)
        disp.addLayout(left); disp.addLayout(right)
        V.addLayout(disp)

        V.addSpacing(6)
        sep=QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background:grey;"); sep.setFixedHeight(2)
        V.addWidget(sep)
        V.addSpacing(4)

        hb=QHBoxLayout()
        save=QPushButton("Save .ahk",clicked=self.save_ahk)
        save.setToolTip("Save script as .ahk file")
        save.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        build=QPushButton("Build .exe",clicked=self.build_exe)
        build.setToolTip("Compile script to executable")
        build.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        hb.addWidget(save,1); hb.addWidget(build,1)
        V.addLayout(hb)

        self.resize(500,500)

    def _pick_into(self,lineedit):
        dlg=KeyPicker(self)
        if dlg.exec():
            lineedit.setText(dlg.result)

    def _add_key(self):
        sel=self.seq.selectedItems()
        dlg=KeyPicker(self)
        if dlg.exec():
            if len(sel)==1:
                sel[0].setText(dlg.result)
            else:
                self.seq.addItem(dlg.result)

    def _add_delay(self):
        sel=self.seq.selectedItems()
        val,ok=QInputDialog.getDouble(self,"Delay (seconds)","Seconds:",1.0,0.0,3600.0,2)
        if ok:
            txt=f"{val:g} s"
            if len(sel)==1:
                sel[0].setText(txt)
            else:
                self.seq.addItem(txt)

    def _add_text(self):
        sel=self.seq.selectedItems()
        txt,ok=QInputDialog.getText(self,"Literal text","Text to send:")
        if ok and txt:
            lit=f'"{txt}"'
            if len(sel)==1:
                sel[0].setText(lit)
            else:
                self.seq.addItem(lit)

    def _seq_context_menu(self,pos):
        sels=self.seq.selectedItems()
        if not sels:
            return
        menu=QMenu(self)
        multi=len(sels)>1
        if not multi:
            editA=menu.addAction("Edit")
        repA=menu.addAction("Replicate")
        remA=menu.addAction("Remove")
        act=menu.exec(self.seq.mapToGlobal(pos))
        if act==remA:
            rows=sorted({self.seq.row(it) for it in sels},reverse=True)
            for r in rows:
                self.seq.takeItem(r)
        elif act==repA:
            for it in sels:
                self.seq.addItem(it.text())
        elif not multi and act==editA:
            it=sels[0]; txt=it.text()
            # detect type
            if m:=re.fullmatch(r"(\d+(?:\.\d+)?)\s*s",txt):
                val=float(m.group(1))
                new,ok=QInputDialog.getDouble(self,"Edit Delay","Seconds:",val,0.0,3600.0,2)
                if ok: it.setText(f"{new:g} s")
            elif txt.startswith('"') and txt.endswith('"'):
                inner=txt[1:-1]
                new,ok=QInputDialog.getText(self,"Edit Text","Text to send:",text=inner)
                if ok: it.setText(f'"{new}"')
            else:
                dlg=KeyPicker(self)
                if dlg.exec(): it.setText(dlg.result)

    def add_mapping(self):
        # toggle control
        t = self.toggle.text().strip()
        if t:
            key = f"Toggle → {t}"
            if 'toggle' not in self.control_items:
                item = QListWidgetItem(key)
                self.maplist.addItem(item)
                self.control_items['toggle'] = item
            else:
                self.control_items['toggle'].setText(key)

        # exit control
        e = self.exit.text().strip()
        if e:
            key = f"Exit → {e}"
            if 'exit' not in self.control_items:
                item = QListWidgetItem(key)
                self.maplist.addItem(item)
                self.control_items['exit'] = item
            else:
                self.control_items['exit'].setText(key)

        # Info control
        i = self.info.text().strip()
        if i:
            key = f"Info → {i}"
            if 'info' not in self.control_items:
                item = QListWidgetItem(key)
                self.maplist.addItem(item)
                self.control_items['info'] = item
            else:
                self.control_items['info'].setText(key)

        # normal mapping (only if you actually picked a trigger + built a sequence)
        trig = self.trigger.text().strip()
        steps = [self.seq.item(j).text() for j in range(self.seq.count())]
        if trig and steps:
            self.maps.append((trig, steps))
            self.maplist.addItem(f"{trig} → {', '.join(steps)}")
            self.trigger.clear()
            self.seq.clear()

        # always refresh the preview, so Toggle/Exit/Info show up immediately
        self._refresh()

    def _maplist_context_menu(self,pos):
        item=self.maplist.itemAt(pos)
        if not item:
            return
        menu=QMenu(self)
        rem=menu.addAction("Remove mapping")
        act=menu.exec(self.maplist.mapToGlobal(pos))
        if act==rem:
            row=self.maplist.row(item)
            if item in self.control_items.values():
                for k,v in list(self.control_items.items()):
                    if v is item:
                        getattr(self,k).clear()
                        del self.control_items[k]
                        break
            else:
                offset=len(self.control_items)
                self.maps.pop(row-offset)
            self.maplist.takeItem(row)
            self._refresh()

    def _reset_all(self):
        ans=QMessageBox.question(self,"Confirm Reset",
                                 "Clear all mappings and inputs?",
                                 QMessageBox.StandardButton.Yes|
                                 QMessageBox.StandardButton.No)
        if ans==QMessageBox.StandardButton.Yes:
            for fld in (self.trigger,self.toggle,self.exit,self.info):
                fld.clear()
            self.seq.clear()
            self.maps.clear()
            self.control_items.clear()
            self.maplist.clear()
            self.preview.clear()
            self._refresh()

    def _refresh(self):
        if not (self.maps or self.toggle.text().strip() or
                self.exit.text().strip()):
            self.preview.clear()
            return

        lines=[
            "; generated by KeyMapper",
            "#Requires AutoHotkey v2.0+",
            "",
            "global scriptEnabled := true",
            "global infoVisible := false",
            ""
        ]
        if t:=self.toggle.text().strip():
            th=hotkey_to_ahk(t)
            lines+=[
                f"{th}:: {{",
                "    global scriptEnabled",
                "    scriptEnabled := !scriptEnabled",
                "    ToolTip(scriptEnabled?\"ENABLED\":\"DISABLED\")",
                "    SetTimer(() => ToolTip(), -1000)",
                "}",
                ""
            ]
        if e:=self.exit.text().strip():
            lines.append(f"{hotkey_to_ahk(e)}::ExitApp")
            lines.append("")
        if i:=self.info.text().strip():
            ih=hotkey_to_ahk(i)
            info_lines=[]
            for hk,steps in self.maps:
                clean=[s[1:-1] if s.startswith('"') and s.endswith('"') else s
                       for s in steps]
                info_lines.append(f"{hk} → {', '.join(clean)}")
            tip="Info:`n"+ "`n".join(info_lines)
            lines+=[
                f"{ih}:: {{",
                "    global infoVisible",
                "    if infoVisible {",
                "        ToolTip()",
                "        infoVisible := false",
                "    } else {",
                f'        ToolTip("{tip}")',
                "        SetTimer(() => ToolTip(), -5000)",
                "        infoVisible := true",
                "    }",
                "}",
                ""
            ]
        lines.append("#HotIf scriptEnabled")
        for hk,steps in self.maps:
            ah=hotkey_to_ahk(hk)
            body=[to_ahk_step(s) for s in steps]
            if len(body)==1:
                lines.append(f"{ah}:: {body[0]}")
            else:
                lines.append(f"{ah}::")
                lines.append("{")
                for b in body:
                    lines.append(f"    {b}")
                lines.append("}")
        lines.append("#HotIf")
        self.preview.setPlainText("\n".join(lines))

    def save_ahk(self):
        p,_=QFileDialog.getSaveFileName(self,"Save AHK","keymap.ahk","AHK (*.ahk)")
        if p:
            Path(p).write_text(self.preview.toPlainText(),encoding="utf-8")

    def build_exe(self):
        exe=shutil.which("Ahk2Exe.exe")
        if not exe:
            QMessageBox.warning(self,"Ahk2Exe not found",
                                "Place Ahk2Exe.exe in PATH.")
            return
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/"temp.ahk"
            src.write_text(self.preview.toPlainText(),encoding="utf-8")
            dst,_=QFileDialog.getSaveFileName(self,"Save EXE","keymap.exe","EXE (*.exe)")
            if dst:
                subprocess.run([exe,"/in",src,"/out",dst],
                               stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                QMessageBox.information(self,"Done",f"Created {dst}")

if __name__=="__main__":
    app=QApplication(sys.argv)
    KeyMapper().show()
    sys.exit(app.exec())
