from __future__ import annotations

import json
import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from http.server import ThreadingHTTPServer
from tkinter import filedialog, messagebox, ttk
from typing import Optional

import proxy
from config_store import AppConfig, MODEL_ENV_KEYS, ModelConfig, config_path, default_claude_path, default_claude_settings_path, load_config, portable_claude_path, portable_settings_path, save_config
from platform_utils import is_windows, launch_claude, launch_script_filename, launch_script_text


class ProxyApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("SHTUClaudeProxy - Guided Setup")
        self.geometry("1280x900")
        self.minsize(1040, 680)
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
        self.model_env_vars = {
            key: tk.StringVar(value=self.config_data.model_env.get(key) or self.config_data.default_model_id)
            for key in MODEL_ENV_KEYS
        }
        self.model_env_combos: list[ttk.Combobox] = []
        self.route_summary_var = tk.StringVar()
        self.scroll_canvas: Optional[tk.Canvas] = None

        self.name_var = tk.StringVar()
        self.model_id_var = tk.StringVar()
        self.base_url_var = tk.StringVar()
        self.api_key_var = tk.StringVar()
        self.upstream_model_var = tk.StringVar()
        self.api_format_var = tk.StringVar(value="responses")
        self.status_var = tk.StringVar(value="Stopped")

        self.configure_styles()
        self.create_widgets()
        self.refresh_model_list()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(300, self.show_first_run_tip)

    def configure_styles(self) -> None:
        style = ttk.Style(self)
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), foreground="#0b3d91")
        style.configure("Success.TButton", font=("Segoe UI", 10, "bold"), foreground="#0f6b2f")
        style.configure("Warning.TButton", font=("Segoe UI", 10, "bold"), foreground="#9a4d00")
        style.configure("StepTitle.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Hint.TLabel", foreground="#555555")
        style.configure("Status.TLabel", font=("Segoe UI", 10, "bold"), foreground="#0f6b2f")

    def create_widgets(self) -> None:
        outer = ttk.Frame(self)
        outer.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(outer, highlightthickness=0)
        self.scroll_canvas = canvas
        scrollbar = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        root = ttk.Frame(canvas, padding=12)
        root_window = canvas.create_window((0, 0), window=root, anchor="nw")

        def update_scroll_region(_event: object) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def update_root_width(event: tk.Event) -> None:
            canvas.itemconfigure(root_window, width=event.width)

        def on_mousewheel(event: tk.Event) -> None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        root.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", update_root_width)
        canvas.bind_all("<MouseWheel>", on_mousewheel)

        intro_frame = ttk.LabelFrame(root, text="Recommended Order")
        intro_frame.pack(fill=tk.X, pady=(0, 10))
        intro_frame.columnconfigure(0, weight=1)
        ttk.Label(
            intro_frame,
            text="Follow 1 -> 2 -> 3 for first-time setup. After that, usually only Step 3 is needed.",
            style="StepTitle.TLabel",
        ).grid(row=0, column=0, padx=10, pady=(8, 2), sticky="w")
        ttk.Label(
            intro_frame,
            text="Advanced buttons are optional. You can ignore them for normal daily use.",
            style="Hint.TLabel",
        ).grid(row=1, column=0, padx=10, pady=(0, 8), sticky="w")

        actions = ttk.LabelFrame(root, text="Quick Start")
        actions.pack(fill=tk.X, pady=(0, 10))
        for column in range(4):
            actions.columnconfigure(column, weight=1)

        self.create_step_card(
            actions,
            0,
            "Fast Start",
            "Save + Connect + Launch",
            "Recommended: write settings, start proxy, and open Claude Code.",
            self.setup_and_launch,
            "Success.TButton",
        )

        self.create_step_card(
            actions,
            1,
            "1. Save",
            "Save Config",
            "Save model, routing, key, URL, and server settings.",
            self.save,
            "Primary.TButton",
        )
        self.create_step_card(
            actions,
            2,
            "2. Connect Claude",
            "Write Claude Settings",
            "One-time setup: write selected model routing to Claude Code.",
            self.write_claude_settings,
            "Warning.TButton",
        )
        self.create_step_card(
            actions,
            3,
            "3. Run",
            "Start Proxy + Launch Claude",
            "Daily use: start proxy, then open Claude Code.",
            self.launch_claude_code,
            "Success.TButton",
        )

        server_frame = ttk.LabelFrame(root, text="Server")
        server_frame.pack(fill=tk.X)
        for column in range(8):
            server_frame.columnconfigure(column, weight=1 if column in (1, 3, 5, 7) else 0)

        ttk.Label(server_frame, text="Host").grid(row=0, column=0, padx=6, pady=8, sticky="w")
        ttk.Entry(server_frame, textvariable=self.host_var, width=16).grid(row=0, column=1, padx=6, pady=8, sticky="ew")
        ttk.Label(server_frame, text="Port").grid(row=0, column=2, padx=6, pady=8, sticky="w")
        ttk.Entry(server_frame, textvariable=self.port_var, width=8).grid(row=0, column=3, padx=6, pady=8, sticky="ew")
        ttk.Label(server_frame, text="Current Main Model").grid(row=0, column=4, padx=6, pady=8, sticky="w")
        ttk.Entry(server_frame, textvariable=self.default_model_var, width=18, state="readonly").grid(row=0, column=5, padx=6, pady=8, sticky="ew")
        ttk.Label(server_frame, text="Timeout").grid(row=0, column=6, padx=6, pady=8, sticky="w")
        ttk.Entry(server_frame, textvariable=self.timeout_var, width=8).grid(row=0, column=7, padx=6, pady=8, sticky="ew")
        ttk.Label(server_frame, text="Claude Code Path").grid(row=1, column=0, padx=6, pady=8, sticky="w")
        ttk.Entry(server_frame, textvariable=self.claude_path_var).grid(row=1, column=1, columnspan=6, padx=6, pady=8, sticky="ew")
        ttk.Button(server_frame, text="Browse", command=self.browse_claude_path).grid(row=1, column=7, padx=6, pady=8, sticky="ew")
        ttk.Label(server_frame, text="Claude Settings Path").grid(row=2, column=0, padx=6, pady=8, sticky="w")
        ttk.Entry(server_frame, textvariable=self.claude_settings_path_var).grid(row=2, column=1, columnspan=6, padx=6, pady=8, sticky="ew")
        ttk.Button(server_frame, text="Browse", command=self.browse_claude_settings_path).grid(row=2, column=7, padx=6, pady=8, sticky="ew")

        env_frame = ttk.LabelFrame(root, text="Claude Model Routing")
        env_frame.pack(fill=tk.X, pady=(6, 0))
        for column in range(5):
            env_frame.columnconfigure(column, weight=1)
        ttk.Label(
            env_frame,
            text="Choose model routing. Defaults can all be the same.",
            style="Hint.TLabel",
        ).grid(row=0, column=0, columnspan=5, padx=8, pady=(6, 2), sticky="w")
        model_routes = [
            ("Main Model", "ANTHROPIC_MODEL"),
            ("Haiku Model", "ANTHROPIC_DEFAULT_HAIKU_MODEL"),
            ("Sonnet Model", "ANTHROPIC_DEFAULT_SONNET_MODEL"),
            ("Opus Model", "ANTHROPIC_DEFAULT_OPUS_MODEL"),
            ("Reasoning Model", "ANTHROPIC_REASONING_MODEL"),
        ]
        for index, (label, key) in enumerate(model_routes):
            route_cell = ttk.Frame(env_frame)
            route_cell.grid(row=1, column=index, padx=5, pady=4, sticky="ew")
            route_cell.columnconfigure(0, weight=1)
            ttk.Label(route_cell, text=label).grid(row=0, column=0, sticky="w")
            combo = ttk.Combobox(route_cell, textvariable=self.model_env_vars[key], state="readonly", width=18)
            combo.grid(row=1, column=0, sticky="ew")
            combo.bind("<<ComboboxSelected>>", self.on_model_route_changed)
            self.model_env_combos.append(combo)
        ttk.Label(env_frame, textvariable=self.route_summary_var, style="StepTitle.TLabel").grid(row=2, column=0, columnspan=5, padx=8, pady=(2, 6), sticky="w")

        body = ttk.Frame(root)
        body.pack(fill=tk.BOTH, expand=True, pady=(8, 6))
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
        list_buttons.grid(row=1, column=0, sticky="ew", pady=4)
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
            ttk.Label(edit_frame, text=label).grid(row=row, column=0, padx=8, pady=4, sticky="w")
            show = "*" if label == "API Key" else None
            ttk.Entry(edit_frame, textvariable=variable, show=show).grid(row=row, column=1, padx=8, pady=4, sticky="ew")
        ttk.Label(edit_frame, text="API Format").grid(row=5, column=0, padx=8, pady=4, sticky="w")
        ttk.Combobox(
            edit_frame,
            textvariable=self.api_format_var,
            values=("responses", "chat_completions"),
            state="readonly",
        ).grid(row=5, column=1, padx=8, pady=4, sticky="ew")

        hint = (
            "Step 1: Fill API Key, Base URL, API Format, and Upstream Model.\n"
            "Claude Code sees Model ID; the upstream service receives Upstream Model."
        )
        ttk.Label(edit_frame, text=hint, style="Hint.TLabel").grid(row=6, column=0, columnspan=2, padx=8, pady=4, sticky="w")
        ttk.Button(edit_frame, text="Apply Model Changes", command=self.apply_model).grid(row=7, column=1, padx=8, pady=4, sticky="e")

        status_frame = ttk.Frame(root)
        status_frame.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(status_frame, text="Status:", style="StepTitle.TLabel").pack(side=tk.LEFT)
        ttk.Label(status_frame, textvariable=self.status_var, style="Status.TLabel").pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(status_frame, text="Stop Proxy", command=self.stop_proxy).pack(side=tk.RIGHT, padx=4)
        ttk.Button(status_frame, text="Start Proxy Only", command=self.start_proxy).pack(side=tk.RIGHT, padx=4)

        advanced = ttk.LabelFrame(root, text="Advanced / Optional")
        advanced.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(
            advanced,
            text="Optional: install a manual PowerShell launcher or copy env vars. Most users do not need these.",
            style="Hint.TLabel",
        ).pack(side=tk.LEFT, padx=8, pady=8)
        ttk.Button(advanced, text="Install Launch Script", command=self.install_launch_script).pack(side=tk.RIGHT, padx=4, pady=8)
        ttk.Button(advanced, text="Copy Claude Config", command=self.copy_claude_config).pack(side=tk.RIGHT, padx=4, pady=8)

        log_frame = ttk.LabelFrame(root, text="Logs")
        log_frame.pack(fill=tk.BOTH, expand=False, pady=(10, 0))
        self.log_text = tk.Text(log_frame, height=5, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def create_step_card(
        self,
        parent: ttk.Frame,
        column: int,
        title: str,
        button_text: str,
        description: str,
        command: object,
        button_style: str,
    ) -> None:
        card = ttk.Frame(parent, padding=6)
        card.grid(row=0, column=column, sticky="nsew", padx=6, pady=6)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1, minsize=36)
        ttk.Label(card, text=title, style="StepTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(card, text=description, style="Hint.TLabel", wraplength=280).grid(row=1, column=0, sticky="new", pady=(2, 6))
        ttk.Button(card, text=button_text, command=command, style=button_style).grid(row=2, column=0, sticky="sew")

    def refresh_model_list(self) -> None:
        self.model_tree.delete(*self.model_tree.get_children())
        for index, model in enumerate(self.config_data.models):
            self.model_tree.insert("", tk.END, iid=str(index), values=(model.model_id, model.upstream_model))
        self.refresh_model_env_choices()
        if self.config_data.models:
            self.model_tree.selection_set("0")
            self.load_model(0)

    def refresh_model_env_choices(self) -> None:
        model_ids = [model.model_id for model in self.config_data.models]
        if not model_ids:
            return
        for key, variable in self.model_env_vars.items():
            if variable.get() not in model_ids:
                variable.set(self.config_data.default_model_id if self.config_data.default_model_id in model_ids else model_ids[0])
        self.default_model_var.set(self.model_env_vars["ANTHROPIC_MODEL"].get())
        for combo in self.model_env_combos:
            combo.configure(values=model_ids)
        self.update_model_route_summary()

    def on_model_route_changed(self, _event: object) -> None:
        self.default_model_var.set(self.model_env_vars["ANTHROPIC_MODEL"].get())
        self.update_model_route_summary()

    def update_model_route_summary(self) -> None:
        labels = (
            ("Main", "ANTHROPIC_MODEL"),
            ("Haiku", "ANTHROPIC_DEFAULT_HAIKU_MODEL"),
            ("Sonnet", "ANTHROPIC_DEFAULT_SONNET_MODEL"),
            ("Opus", "ANTHROPIC_DEFAULT_OPUS_MODEL"),
            ("Reasoning", "ANTHROPIC_REASONING_MODEL"),
        )
        summary = "Effective: " + " | ".join(f"{label}={self.model_env_vars[key].get()}" for label, key in labels)
        self.route_summary_var.set(summary)

    def selected_model_env(self) -> dict[str, str]:
        model_ids = [model.model_id for model in self.config_data.models]
        fallback = self.config_data.default_model_id if self.config_data.default_model_id in model_ids else model_ids[0]
        selected = {}
        for key, variable in self.model_env_vars.items():
            value = variable.get().strip()
            selected[key] = value if value in model_ids else fallback
            variable.set(selected[key])
        selected["ANTHROPIC_MODEL"] = self.model_env_vars["ANTHROPIC_MODEL"].get().strip() or fallback
        self.default_model_var.set(selected["ANTHROPIC_MODEL"])
        self.update_model_route_summary()
        return selected

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
        self.api_format_var.set(getattr(model, "api_format", "responses") or "responses")

    def needs_first_run_setup(self) -> bool:
        return not any(model.api_key.strip() for model in self.config_data.models)

    def show_first_run_tip(self) -> None:
        if not self.needs_first_run_setup():
            return
        messagebox.showinfo(
            "First-time setup",
            "Welcome to SHTUClaudeProxy.\n\n"
            "For first-time use, you usually only need to:\n"
            "1. Paste your GenAI API Key in Model Config.\n"
            "2. Confirm Base URL / API Format / Upstream Model.\n"
            "3. Click Save Config.\n"
            "4. Click Write Claude Settings.\n"
            "5. Click Start Proxy + Launch Claude.\n\n"
            "No Python installation is required when using the release EXE."
        )

    def new_model(self) -> None:
        model = ModelConfig(
            name="New Model",
            model_id="new-model-id",
            base_url="https://genaiapi.shanghaitech.edu.cn/api/v1/response",
            api_key="",
            upstream_model="GPT-5.5",
            api_format="responses",
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
        old_model_id = self.config_data.models[self.selected_index].model_id
        model = ModelConfig(
            name=self.name_var.get().strip() or self.model_id_var.get().strip(),
            model_id=self.model_id_var.get().strip(),
            base_url=self.base_url_var.get().strip(),
            api_key=self.api_key_var.get().strip(),
            upstream_model=self.upstream_model_var.get().strip() or self.model_id_var.get().strip(),
            api_format=self.api_format_var.get().strip() or "responses",
        )
        if not model.model_id or not model.base_url:
            messagebox.showerror("Missing value", "Model ID and Base URL are required.")
            return
        if old_model_id != model.model_id:
            for variable in self.model_env_vars.values():
                if variable.get() == old_model_id:
                    variable.set(model.model_id)
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
        self.config_data.model_env = self.selected_model_env()
        self.config_data.default_model_id = self.config_data.model_env["ANTHROPIC_MODEL"]
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
        env = self.claude_env()
        if not env:
            return
        value = json.dumps({"env": env, "includeCoAuthoredBy": False}, ensure_ascii=False, indent=2)
        self.clipboard_clear()
        self.clipboard_append(value)
        self.append_log("Copied Claude Code config to clipboard")

    def claude_env(self) -> dict[str, str]:
        if not self.sync_server_fields():
            return {}
        env = {
            "ANTHROPIC_BASE_URL": f"http://{self.config_data.host}:{self.config_data.port}",
            "ANTHROPIC_AUTH_TOKEN": "local-proxy",
        }
        env.update(self.config_data.model_env)
        return env


    def claude_settings_payload(self) -> dict[str, object]:
        return {
            "env": self.claude_env(),
            "includeCoAuthoredBy": False,
        }

    def write_claude_settings(self, notify: bool = True) -> bool:
        self.save()
        if self.needs_first_run_setup():
            messagebox.showwarning("API key required", "Please paste your GenAI API Key before writing Claude settings.")
            return False
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
        if notify:
            messagebox.showinfo("Claude settings written", f"Updated env in:\n{settings_path}\n\nProxy is running at http://{self.config_data.host}:{self.config_data.port}. Restart Claude Code to use it.")
        return True

    def setup_and_launch(self) -> None:
        if not self.write_claude_settings(notify=False):
            return
        self.launch_claude_code()

    def launch_script_text(self) -> str:
        env = self.claude_env()
        if not env:
            return ""
        return launch_script_text(env, self.config_data.claude_path)

    def install_launch_script(self) -> None:
        self.save()
        script = self.launch_script_text()
        if not script:
            return
        target_dir = Path.home() / "shtu-claude-proxy"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / launch_script_filename()
        target.write_text(script, encoding="utf-8")
        if not is_windows():
            target.chmod(0o755)
        self.clipboard_clear()
        self.clipboard_append(str(target))
        self.append_log(f"Installed Claude launch script: {target}")
        run_hint = (
            f'powershell -ExecutionPolicy Bypass -File "{target}"'
            if is_windows()
            else f'"{target}"'
        )
        messagebox.showinfo(
            "Launch script installed",
            f"Script saved and path copied:\n{target}\n\nRun it with:\n{run_hint}",
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
            launch_claude(claude_path, env_values)
            self.append_log("Launched Claude Code with SHTUClaudeProxy environment")
        except Exception as exc:
            messagebox.showerror("Launch failed", str(exc))

    def append_log(self, message: str) -> None:
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)

    def on_close(self) -> None:
        if self.scroll_canvas is not None:
            self.scroll_canvas.unbind_all("<MouseWheel>")
        self.stop_proxy()
        self.destroy()


if __name__ == "__main__":
    ProxyApp().mainloop()




