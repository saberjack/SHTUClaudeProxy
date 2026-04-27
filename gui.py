from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from http.server import ThreadingHTTPServer
from tkinter import filedialog, messagebox, ttk
from typing import Optional

import proxy
from config_store import AppConfig, ModelConfig, config_path, default_claude_path, default_claude_settings_path, load_config, portable_claude_path, portable_settings_path, save_config


class ProxyApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("SHTUClaudeProxy")
        self.geometry("940x640")
        self.minsize(860, 560)
        self.config_data = load_config()
        self.server: Optional[ThreadingHTTPServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self.selected_index: Optional[int] = None

        self.host_var = tk.StringVar(value=self.config_data.host)
        self.port_var = tk.StringVar(value=str(self.config_data.port))
        self.default_model_var = tk.StringVar(value=self.config_data.default_model_id)
        self.timeout_var = tk.StringVar(value=str(self.config_data.timeout))
        self.claude_path_var = tk.StringVar(value=self.config_data.claude_path)
        self.claude_settings_path_var = tk.StringVar(value=self.config_data.claude_settings_path)

        self.name_var = tk.StringVar()
        self.model_id_var = tk.StringVar()
        self.base_url_var = tk.StringVar()
        self.api_key_var = tk.StringVar()
        self.upstream_model_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Stopped")

        self.create_widgets()
        self.refresh_model_list()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def create_widgets(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        server_frame = ttk.LabelFrame(root, text="Server")
        server_frame.pack(fill=tk.X)
        for column in range(8):
            server_frame.columnconfigure(column, weight=1 if column in (1, 3, 5, 7) else 0)

        ttk.Label(server_frame, text="Host").grid(row=0, column=0, padx=6, pady=8, sticky="w")
        ttk.Entry(server_frame, textvariable=self.host_var, width=16).grid(row=0, column=1, padx=6, pady=8, sticky="ew")
        ttk.Label(server_frame, text="Port").grid(row=0, column=2, padx=6, pady=8, sticky="w")
        ttk.Entry(server_frame, textvariable=self.port_var, width=8).grid(row=0, column=3, padx=6, pady=8, sticky="ew")
        ttk.Label(server_frame, text="Default Model ID").grid(row=0, column=4, padx=6, pady=8, sticky="w")
        ttk.Entry(server_frame, textvariable=self.default_model_var, width=18).grid(row=0, column=5, padx=6, pady=8, sticky="ew")
        ttk.Label(server_frame, text="Timeout").grid(row=0, column=6, padx=6, pady=8, sticky="w")
        ttk.Entry(server_frame, textvariable=self.timeout_var, width=8).grid(row=0, column=7, padx=6, pady=8, sticky="ew")
        ttk.Label(server_frame, text="Claude Code Path").grid(row=1, column=0, padx=6, pady=8, sticky="w")
        ttk.Entry(server_frame, textvariable=self.claude_path_var).grid(row=1, column=1, columnspan=6, padx=6, pady=8, sticky="ew")
        ttk.Button(server_frame, text="Browse", command=self.browse_claude_path).grid(row=1, column=7, padx=6, pady=8, sticky="ew")
        ttk.Label(server_frame, text="Claude Settings Path").grid(row=2, column=0, padx=6, pady=8, sticky="w")
        ttk.Entry(server_frame, textvariable=self.claude_settings_path_var).grid(row=2, column=1, columnspan=6, padx=6, pady=8, sticky="ew")
        ttk.Button(server_frame, text="Browse", command=self.browse_claude_settings_path).grid(row=2, column=7, padx=6, pady=8, sticky="ew")

        body = ttk.Frame(root)
        body.pack(fill=tk.BOTH, expand=True, pady=10)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        list_frame = ttk.LabelFrame(body, text="Models")
        list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        self.model_tree = ttk.Treeview(list_frame, columns=("model_id", "upstream"), show="headings", selectmode="browse")
        self.model_tree.heading("model_id", text="Model ID")
        self.model_tree.heading("upstream", text="Upstream Model")
        self.model_tree.column("model_id", width=140)
        self.model_tree.column("upstream", width=140)
        self.model_tree.grid(row=0, column=0, sticky="nsew")
        self.model_tree.bind("<<TreeviewSelect>>", self.on_select_model)

        list_buttons = ttk.Frame(list_frame)
        list_buttons.grid(row=1, column=0, sticky="ew", pady=8)
        ttk.Button(list_buttons, text="New", command=self.new_model).pack(side=tk.LEFT, padx=4)
        ttk.Button(list_buttons, text="Delete", command=self.delete_model).pack(side=tk.LEFT, padx=4)

        edit_frame = ttk.LabelFrame(body, text="Model Config")
        edit_frame.grid(row=0, column=1, sticky="nsew")
        edit_frame.columnconfigure(1, weight=1)

        fields = [
            ("Display Name", self.name_var),
            ("Model ID for Claude Code", self.model_id_var),
            ("Responses Base URL", self.base_url_var),
            ("API Key", self.api_key_var),
            ("Upstream Model", self.upstream_model_var),
        ]
        for row, (label, variable) in enumerate(fields):
            ttk.Label(edit_frame, text=label).grid(row=row, column=0, padx=8, pady=7, sticky="w")
            show = "*" if label == "API Key" else None
            ttk.Entry(edit_frame, textvariable=variable, show=show).grid(row=row, column=1, padx=8, pady=7, sticky="ew")

        hint = (
            "Claude Code uses Model ID. The proxy sends Upstream Model to your Responses endpoint.\n"
            "Example: Model ID = gpt-5.5-code, Upstream Model = GPT-5.5"
        )
        ttk.Label(edit_frame, text=hint, foreground="#555").grid(row=5, column=0, columnspan=2, padx=8, pady=8, sticky="w")
        ttk.Button(edit_frame, text="Apply Model Changes", command=self.apply_model).grid(row=6, column=1, padx=8, pady=8, sticky="e")

        bottom = ttk.Frame(root)
        bottom.pack(fill=tk.X)
        ttk.Label(bottom, textvariable=self.status_var).pack(side=tk.LEFT)
        ttk.Button(bottom, text="Save Config", command=self.save).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bottom, text="Start Proxy", command=self.start_proxy).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bottom, text="Stop Proxy", command=self.stop_proxy).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bottom, text="Launch Claude Code", command=self.launch_claude_code).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bottom, text="Write Claude Settings", command=self.write_claude_settings).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bottom, text="Install Launch Script", command=self.install_launch_script).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bottom, text="Copy Claude Config", command=self.copy_claude_config).pack(side=tk.RIGHT, padx=4)

        log_frame = ttk.LabelFrame(root, text="Logs")
        log_frame.pack(fill=tk.BOTH, expand=False, pady=(10, 0))
        self.log_text = tk.Text(log_frame, height=9, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def refresh_model_list(self) -> None:
        self.model_tree.delete(*self.model_tree.get_children())
        for index, model in enumerate(self.config_data.models):
            self.model_tree.insert("", tk.END, iid=str(index), values=(model.model_id, model.upstream_model))
        if self.config_data.models:
            self.model_tree.selection_set("0")
            self.load_model(0)

    def on_select_model(self, _event: object) -> None:
        selection = self.model_tree.selection()
        if selection:
            self.load_model(int(selection[0]))

    def load_model(self, index: int) -> None:
        self.selected_index = index
        model = self.config_data.models[index]
        self.name_var.set(model.name)
        self.model_id_var.set(model.model_id)
        self.base_url_var.set(model.base_url)
        self.api_key_var.set(model.api_key)
        self.upstream_model_var.set(model.upstream_model)

    def new_model(self) -> None:
        model = ModelConfig(
            name="New Model",
            model_id="new-model-id",
            base_url="https://genaiapi.shanghaitech.edu.cn/api/v1/response",
            api_key="",
            upstream_model="GPT-5.5",
        )
        self.config_data.models.append(model)
        self.refresh_model_list()
        index = len(self.config_data.models) - 1
        self.model_tree.selection_set(str(index))
        self.load_model(index)

    def delete_model(self) -> None:
        if self.selected_index is None or not self.config_data.models:
            return
        if len(self.config_data.models) == 1:
            messagebox.showwarning("Cannot delete", "Keep at least one model.")
            return
        del self.config_data.models[self.selected_index]
        self.selected_index = None
        self.refresh_model_list()

    def apply_model(self) -> None:
        if self.selected_index is None:
            return
        model = ModelConfig(
            name=self.name_var.get().strip() or self.model_id_var.get().strip(),
            model_id=self.model_id_var.get().strip(),
            base_url=self.base_url_var.get().strip(),
            api_key=self.api_key_var.get().strip(),
            upstream_model=self.upstream_model_var.get().strip() or self.model_id_var.get().strip(),
        )
        if not model.model_id or not model.base_url:
            messagebox.showerror("Missing value", "Model ID and Base URL are required.")
            return
        self.config_data.models[self.selected_index] = model
        self.refresh_model_list()
        self.model_tree.selection_set(str(self.selected_index))
        self.append_log(f"Applied model {model.model_id}")


    def browse_claude_path(self) -> None:
        initial = self.claude_path_var.get().strip()
        initial_dir = str(Path(initial).parent) if initial and Path(initial).parent.exists() else str(Path.home())
        selected = filedialog.askopenfilename(
            title="Select Claude Code executable",
            initialdir=initial_dir,
            filetypes=[("Claude executable", "claude.cmd claude.exe"), ("Command files", "*.cmd"), ("Executables", "*.exe"), ("All files", "*.*")],
        )
        if selected:
            self.claude_path_var.set(selected)

    def browse_claude_settings_path(self) -> None:
        initial = self.claude_settings_path_var.get().strip()
        initial_dir = str(Path(initial).parent) if initial and Path(initial).parent.exists() else str(Path.home() / ".claude")
        selected = filedialog.askopenfilename(
            title="Select Claude settings.json",
            initialdir=initial_dir,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if selected:
            self.claude_settings_path_var.set(selected)

    def sync_server_fields(self) -> bool:
        try:
            port = int(self.port_var.get().strip())
            timeout = int(self.timeout_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid number", "Port and timeout must be numbers.")
            return False
        self.config_data.host = self.host_var.get().strip() or "127.0.0.1"
        self.config_data.port = port
        self.config_data.default_model_id = self.default_model_var.get().strip() or self.config_data.models[0].model_id
        self.config_data.timeout = timeout
        self.config_data.claude_path = portable_claude_path(self.claude_path_var.get().strip() or default_claude_path())
        self.config_data.claude_settings_path = portable_settings_path(self.claude_settings_path_var.get().strip() or default_claude_settings_path())
        return True

    def save(self) -> None:
        self.apply_model()
        if not self.sync_server_fields():
            return
        save_config(self.config_data)
        self.append_log(f"Saved config: {config_path()}")

    def start_proxy(self) -> None:
        if self.server:
            messagebox.showinfo("Already running", "Proxy is already running.")
            return
        self.save()
        proxy.ACTIVE_CONFIG = self.config_data
        try:
            self.server = ThreadingHTTPServer(
                (self.config_data.host, self.config_data.port),
                proxy.ProxyHandler,
            )
        except OSError as exc:
            self.server = None
            messagebox.showerror("Start failed", str(exc))
            return
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.server_thread.start()
        self.status_var.set(f"Running on http://{self.config_data.host}:{self.config_data.port}")
        self.append_log(f"Proxy started on http://{self.config_data.host}:{self.config_data.port}")

    def stop_proxy(self) -> None:
        if self.server:
            server = self.server
            self.server = None
            server.shutdown()
            server.server_close()
            self.status_var.set("Stopped")
            self.append_log("Stopped proxy")

    def copy_claude_config(self) -> None:
        if not self.sync_server_fields():
            return
        model_id = self.default_model_var.get().strip() or self.config_data.models[0].model_id
        value = f'''{{
  "env": {{
    "ANTHROPIC_BASE_URL": "http://{self.config_data.host}:{self.config_data.port}",
    "ANTHROPIC_MODEL": "{model_id}",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "{model_id}",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "{model_id}",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "{model_id}",
    "ANTHROPIC_AUTH_TOKEN": "local-proxy"
  }},
  "includeCoAuthoredBy": false
}}'''
        self.clipboard_clear()
        self.clipboard_append(value)
        self.append_log("Copied Claude Code config to clipboard")

    def claude_env(self) -> dict[str, str]:
        if not self.sync_server_fields():
            return {}
        model_id = self.default_model_var.get().strip() or self.config_data.models[0].model_id
        return {
            "ANTHROPIC_BASE_URL": f"http://{self.config_data.host}:{self.config_data.port}",
            "ANTHROPIC_MODEL": model_id,
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": model_id,
            "ANTHROPIC_DEFAULT_SONNET_MODEL": model_id,
            "ANTHROPIC_DEFAULT_OPUS_MODEL": model_id,
            "ANTHROPIC_REASONING_MODEL": model_id,
            "ANTHROPIC_AUTH_TOKEN": "local-proxy",
        }


    def claude_settings_payload(self) -> dict[str, object]:
        return {
            "env": self.claude_env(),
            "includeCoAuthoredBy": False,
        }

    def write_claude_settings(self) -> None:
        self.save()
        settings_path = Path(self.config_data.claude_settings_path).expanduser()
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        existing: dict[str, object] = {}
        if settings_path.exists():
            try:
                existing = json.loads(settings_path.read_text(encoding="utf-8-sig"))
            except Exception:
                backup = settings_path.with_suffix(settings_path.suffix + ".bak")
                backup.write_bytes(settings_path.read_bytes())
                self.append_log(f"Backed up unreadable settings to {backup}")
        env = existing.get("env") if isinstance(existing.get("env"), dict) else {}
        env.update(self.claude_env())
        existing["env"] = env
        existing["includeCoAuthoredBy"] = False
        settings_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        self.append_log(f"Wrote Claude settings env: {settings_path}")
        if not self.server:
            self.start_proxy()
        messagebox.showinfo("Claude settings written", f"Updated env in:\n{settings_path}\n\nProxy is running at http://{self.config_data.host}:{self.config_data.port}. Restart Claude Code to use it.")

    def launch_script_text(self) -> str:
        env = self.claude_env()
        if not env:
            return ""
        lines = [
            "$ErrorActionPreference = \"Stop\"",
            "# Generated by SHTUClaudeProxy",
        ]
        for key, value in env.items():
            escaped = value.replace("'", "''")
            lines.append(f"$env:{key} = '{escaped}'")
        lines.extend([
            "Write-Host 'SHTUClaudeProxy config loaded.' -ForegroundColor Green",
            f"Write-Host 'ANTHROPIC_BASE_URL={env['ANTHROPIC_BASE_URL']}'",
            f"Write-Host 'ANTHROPIC_MODEL={env['ANTHROPIC_MODEL']}'",
            f"& '{self.config_data.claude_path.replace(chr(39), chr(39) + chr(39))}' @args",
        ])
        return "\n".join(lines) + "\n"

    def install_launch_script(self) -> None:
        self.save()
        script = self.launch_script_text()
        if not script:
            return
        target_dir = Path.home() / "shtu-claude-proxy"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "claude-shtu.ps1"
        target.write_text(script, encoding="utf-8")
        self.clipboard_clear()
        self.clipboard_append(str(target))
        self.append_log(f"Installed Claude launch script: {target}")
        messagebox.showinfo(
            "Launch script installed",
            f"Script saved and path copied:\n{target}\n\nRun it in PowerShell instead of cc-switch: powershell -ExecutionPolicy Bypass -File \"{target}\"",
        )

    def launch_claude_code(self) -> None:
        self.save()
        if not self.server:
            self.start_proxy()
        env_values = self.claude_env()
        if not env_values:
            return
        env = os.environ.copy()
        env.update(env_values)
        claude_path = self.config_data.claude_path or "claude"
        try:
            subprocess.Popen(
                ["powershell.exe", "-NoExit", "-Command", f"& '{claude_path.replace(chr(39), chr(39) + chr(39))}'"],
                env=env,
                cwd=str(Path.home()),
                creationflags=subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, "CREATE_NEW_CONSOLE") else 0,
            )
            self.append_log("Launched Claude Code with SHTUClaudeProxy environment")
        except Exception as exc:
            messagebox.showerror("Launch failed", str(exc))

    def append_log(self, message: str) -> None:
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)

    def on_close(self) -> None:
        self.stop_proxy()
        self.destroy()


if __name__ == "__main__":
    ProxyApp().mainloop()




