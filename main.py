import sys, re, subprocess, tempfile, time
from pathlib import Path
from PyQt6.QtCore import Qt, QCoreApplication
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

        # ───────── Toggle + Exit + Info row ─────────
        te_row = QHBoxLayout()
        FIELD_WIDTH = 116

        def make_control(field_name, placeholder):
            fld = QLineEdit()
            fld.setFixedWidth(FIELD_WIDTH)
            fld.setPlaceholderText(placeholder)
            fld.setClearButtonEnabled(True)
            fld.setToolTip(placeholder)
            # click → key picker
            orig = fld.mousePressEvent

            def on_mouse(ev):
                self._pick_into(fld)
                orig(ev)

            fld.mousePressEvent = on_mouse
            # any keypress → key picker
            fld.keyPressEvent = lambda ev: self._pick_into(fld)
            # clear “×” → remove mapping
            fld.textChanged.connect(lambda txt, n=field_name:
                                    self._on_control_cleared(n, txt))
            return fld

        # Instantiate the three control fields and their pick-buttons
        self.toggle = make_control("toggle", "Toggle hot-key")
        btn_toggle = QPushButton("⌨")
        btn_toggle.setFixedWidth(FIELD_WIDTH // 4)
        btn_toggle.setToolTip("Pick toggle hotkey")
        btn_toggle.clicked.connect(lambda: self._pick_into(self.toggle))

        self.exit = make_control("exit", "Exit hot-key")
        btn_exit = QPushButton("⌨")
        btn_exit.setFixedWidth(FIELD_WIDTH // 4)
        btn_exit.setToolTip("Pick exit hotkey")
        btn_exit.clicked.connect(lambda: self._pick_into(self.exit))

        self.info = make_control("info", "Info hot-key")
        btn_info = QPushButton("⌨")
        btn_info.setFixedWidth(FIELD_WIDTH // 4)
        btn_info.setToolTip("Pick info hotkey")
        btn_info.clicked.connect(lambda: self._pick_into(self.info))

        # Add them to the row
        te_row.addWidget(self.toggle);
        te_row.addWidget(btn_toggle)
        te_row.addSpacing(10)
        te_row.addWidget(self.exit);
        te_row.addWidget(btn_exit)
        te_row.addSpacing(10)
        te_row.addWidget(self.info);
        te_row.addWidget(btn_info)
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

    def _on_control_cleared(self, control_name: str, text: str):
        # only act on an actual clear
        if text:
            return
        if control_name in self.control_items:
            item = self.control_items.pop(control_name)
            row  = self.maplist.row(item)
            self.maplist.takeItem(row)
            self._refresh()

    def _add_key(self):
        sel=self.seq.selectedItems()
        dlg=KeyPicker(self)
        if dlg.exec():
            if len(sel)==1:
                sel[0].setText(dlg.result)
                self.seq.clearSelection()
            else:
                self.seq.addItem(dlg.result)

    def _add_delay(self):
        sel=self.seq.selectedItems()
        val,ok=QInputDialog.getDouble(self,"Delay (seconds)","Seconds:",1.0,0.0,3600.0,2)
        if ok:
            txt=f"{val:g} s"
            if len(sel)==1:
                sel[0].setText(txt)
                self.seq.clearSelection()
            else:
                self.seq.addItem(txt)

    def _add_text(self):
        sel=self.seq.selectedItems()
        txt,ok=QInputDialog.getText(self,"Literal text","Text to send:")
        if ok and txt:
            lit=f'"{txt}"'
            if len(sel)==1:
                sel[0].setText(lit)
                self.seq.clearSelection()
            else:
                self.seq.addItem(lit)

    def _seq_context_menu(self, pos):
        sels = self.seq.selectedItems()
        if not sels:
            return

        menu = QMenu(self)
        multi = len(sels) > 1
        if not multi:
            editA = menu.addAction("Edit")
        repA = menu.addAction("Replicate")
        remA = menu.addAction("Remove")
        act = menu.exec(self.seq.mapToGlobal(pos))

        if act == remA:
            rows = sorted({self.seq.row(it) for it in sels}, reverse=True)
            for r in rows:
                # only remove if the index is still valid
                if 0 <= r < self.seq.count():
                    self.seq.takeItem(r)

        elif act == repA:
            for it in sels:
                self.seq.addItem(it.text())

        elif not multi and act == editA:
            it=sels[0]; txt=it.text()
            # detect type
            if m:=re.fullmatch(r"(\d+(?:\.\d+)?)\s*s",txt):
                val=float(m.group(1))
                new,ok=QInputDialog.getDouble(self,"Edit Delay","Seconds:",val,0.0,3600.0,2)
                if ok:
                    it.setText(f"{new:g} s")
                    self.seq.clearSelection()
            elif txt.startswith('"') and txt.endswith('"'):
                inner=txt[1:-1]
                new,ok=QInputDialog.getText(self,"Edit Text","Text to send:",text=inner)
                if ok:
                    it.setText(f'"{new}"')
                    self.seq.clearSelection()
            else:
                dlg=KeyPicker(self)
                if dlg.exec():
                    it.setText(dlg.result)
                    self.seq.clearSelection()

    def add_mapping(self):
        from collections import Counter

        # ─── 1) no duplicates among trigger/toggle/exit/info ───
        fields = {
            'Trigger': self.trigger.text().strip(),
            'Toggle': self.toggle.text().strip(),
            'Exit': self.exit.text().strip(),
            'Info': self.info.text().strip(),
        }
        # only non‐blank
        used = [v for v in fields.values() if v]
        dupes = [k for k, v in Counter(used).items() if v > 1]
        if dupes:
            QMessageBox.warning(
                self,
                "Hotkey Conflict",
                f"Hotkey “{dupes[0]}” is assigned more than once!"
            )
            return

        # ─── 2) no control-field may clash with an existing mapping’s trigger ───
        existing_trigs = [t for t, _ in self.maps]
        for name in ('Toggle', 'Exit', 'Info'):
            key = fields[name]
            if key and key in existing_trigs:
                QMessageBox.warning(
                    self,
                    "Hotkey Conflict",
                    f"{name} hotkey “{key}” is already assigned to function!"
                )
                return

        # ─── 3) no new trigger may clash with existing triggers ───
        trig = fields['Trigger']
        steps = [self.seq.item(i).text() for i in range(self.seq.count())]
        if trig and steps and trig in existing_trigs:
            QMessageBox.warning(
                self,
                "Hotkey Conflict",
                f"Trigger hotkey “{trig}” is already mapped to another sequence."
            )
            return

        # ─── 4) proceed to add/update your controls exactly as before ───
        t = fields['Toggle']
        if t:
            disp = f"Toggle → {t}"
            if 'toggle' not in self.control_items:
                item = QListWidgetItem(disp)
                self.maplist.addItem(item)
                self.control_items['toggle'] = item
            else:
                self.control_items['toggle'].setText(disp)

        e = fields['Exit']
        if e:
            disp = f"Exit → {e}"
            if 'exit' not in self.control_items:
                item = QListWidgetItem(disp)
                self.maplist.addItem(item)
                self.control_items['exit'] = item
            else:
                self.control_items['exit'].setText(disp)

        i = fields['Info']
        if i:
            disp = f"Info → {i}"
            if 'info' not in self.control_items:
                item = QListWidgetItem(disp)
                self.maplist.addItem(item)
                self.control_items['info'] = item
            else:
                self.control_items['info'].setText(disp)

        # ─── 5) add the normal trigger→sequence mapping ───
        if trig and steps:
            self.maps.append((trig, steps))
            self.maplist.addItem(f"{trig} → {', '.join(steps)}")
            self.trigger.clear()
            self.seq.clear()

        # ─── 6) rebuild the script preview ───
        self._refresh()

    def _maplist_context_menu(self, pos):
        item = self.maplist.itemAt(pos)
        if not item:
            return

        menu = QMenu(self)
        rem = menu.addAction("Remove mapping")
        if menu.exec(self.maplist.mapToGlobal(pos)) != rem:
            return

        row = self.maplist.row(item)

        # 1) If this is one of the toggle/exit/info controls, clear that field
        for field, ctrl_item in list(self.control_items.items()):
            if ctrl_item is item:
                getattr(self, field).clear()
                # _on_control_cleared will actually drop it from the list & refresh
                return

        # 2) Otherwise it’s one of your normal hotkey→sequence mappings.
        #    Count how many control-fields actually precede this row:
        ctrl_rows = [self.maplist.row(ci) for ci in self.control_items.values()]
        num_above = sum(1 for r in ctrl_rows if r < row)

        idx = row - num_above
        if 0 <= idx < len(self.maps):
            # remove from your internal list
            self.maps.pop(idx)
            # remove from the UI
            self.maplist.takeItem(row)
            # rebuild the preview
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
        if not self.maps and not self.control_items:
            QMessageBox.warning(self, "Key Map Empty", "You have no mappings defined!")
            return
        p,_=QFileDialog.getSaveFileName(self,"Save AHK","keymap.ahk","AHK (*.ahk)")
        if p:
            Path(p).write_text(self.preview.toPlainText(),encoding="utf-8")

    def build_exe(self):
        if not self.maps and not self.control_items:
            QMessageBox.warning(self, "Key Map Empty", "You have no mappings defined!")
            return

        compiler_dir = Path(r"C:\Program Files\AutoHotkey\Compiler")
        ahk2exe_path = compiler_dir / "Ahk2Exe.exe"
        installer_ahk = Path(r"C:\Program Files\AutoHotkey\UX\install-ahk2exe.ahk")

        # 1) Prompt once if Ahk2Exe.exe is missing
        if not ahk2exe_path.exists():
            dlg = QMessageBox(self)
            dlg.setWindowTitle("Ahk2Exe Not Found")
            dlg.setText("Ahk2Exe.exe is required to compile your script.")
            dlg.setInformativeText("Install it, locate it manually, or cancel:")
            btn_install = dlg.addButton("Install", QMessageBox.ButtonRole.AcceptRole)
            btn_browse = dlg.addButton("Browse", QMessageBox.ButtonRole.AcceptRole)
            btn_cancel = dlg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            dlg.exec()

            # — INSTALL
            if dlg.clickedButton() == btn_install:
                if not installer_ahk.exists():
                    QMessageBox.warning(self, "Installer Missing",
                                        "install-ahk2exe.ahk wasn’t found in UX folder.")
                    return
                try:
                    subprocess.run(
                        ["autohotkey.exe", str(installer_ahk)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=True
                    )
                except FileNotFoundError:
                    QMessageBox.warning(self, "AutoHotkey Not Found",
                                        "Cannot find AutoHotkey.exe in your PATH.")
                    return
                except subprocess.CalledProcessError:
                    QMessageBox.warning(self, "Installer Failed",
                                        "Ahk2Exe installer didn’t complete successfully.")
                    return

                # wait & kill installer GUI
                for _ in range(25):
                    proc = subprocess.run(
                        ["tasklist", "/FI", "IMAGENAME eq Ahk2Exe.exe", "/NH"],
                        capture_output=True, text=True
                    )
                    if "Ahk2Exe.exe" in proc.stdout:
                        subprocess.run(
                            ["taskkill", "/F", "/IM", "Ahk2Exe.exe"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                        )
                        break
                    time.sleep(0.2)

                # poll up to 15s for the EXE file to appear
                timeout, interval, elapsed = 15.0, 0.5, 0.0
                while elapsed < timeout:
                    if ahk2exe_path.exists():
                        break
                    QCoreApplication.processEvents()
                    time.sleep(interval)
                    elapsed += interval

                if not ahk2exe_path.exists():
                    QMessageBox.warning(self, "Still Missing",
                                        "Ahk2Exe.exe did not appear after installation.")
                    return
                # falls through…

            # — BROWSE
            elif dlg.clickedButton() == btn_browse:
                path, _ = QFileDialog.getOpenFileName(
                    self, "Locate Ahk2Exe.exe", "", "Executable (*.exe)"
                )
                if not path or Path(path).name.lower() != "ahk2exe.exe":
                    QMessageBox.warning(self, "Invalid File", "That isn’t an Ahk2Exe.exe!")
                    return
                ahk2exe_path = Path(path)

            # — CANCEL
            else:
                return

        # 2) Ask where to save the compiled .exe
        out_file, _ = QFileDialog.getSaveFileName(
            self, "Save EXE", "keymap.exe", "EXE (*.exe)"
        )
        if not out_file:
            return

        # 3) Dump preview to a temp .ahk
        with tempfile.TemporaryDirectory() as tmp:
            temp_ahk = Path(tmp) / "temp.ahk"
            temp_ahk.write_text(self.preview.toPlainText(), encoding="utf-8")

            # 4) Auto-pick the correct v2 runtime
            is_64 = sys.maxsize > 2 ** 32
            v2dir = Path(r"C:\Program Files\AutoHotkey\v2")
            ahk64 = v2dir / "AutoHotkey64.exe"
            ahk32 = v2dir / "AutoHotkey32.exe"

            if is_64 and ahk64.exists():
                base = ahk64
            elif ahk32.exists():
                base = ahk32
            else:
                base_path, _ = QFileDialog.getOpenFileName(
                    self, "Locate AutoHotkey.exe", "", "Executable (*.exe)"
                )
                if not base_path:
                    return
                base = Path(base_path)

            # 5) Compile, passing /bin for the base
            try:
                subprocess.run(
                    [
                        str(ahk2exe_path),
                        "/in", str(temp_ahk),
                        "/out", out_file,
                        "/bin", str(base)
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE
                )
                QMessageBox.information(self, "Success",
                                        f"Executable created at:\n{out_file}")
            except subprocess.CalledProcessError as e:
                err = e.stderr.decode(errors="ignore")
                QMessageBox.critical(self, "Compile Failed", err or "Unknown error.")


if __name__=="__main__":
    app=QApplication(sys.argv)
    KeyMapper().show()
    sys.exit(app.exec())
