"""
main.py
Tkinter GUI with Scrollable Outer Canvas for Decentralized P2P App.
Direct Peer-to-Peer messaging & file transfer.
"""

from __future__ import annotations

import socket
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

from p2p_node import P2PNode


class P2PApplication(tk.Tk):
    """Desktop GUI application."""

    def __init__(self) -> None:
        super().__init__()

        self.title("CSE 433 - Decentralized P2P Communication & File Sharing")
        self.geometry("1000x720")
        self.minsize(800, 550)

        self.node: P2PNode | None = None

        self._build_variables()
        self._build_style()
        self._build_ui()
        self._set_running_state(False)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _build_variables(self) -> None:
        self.name_var = tk.StringVar(value="Peer")
        self.port_var = tk.StringVar(value="5000")

        self.ip_var = tk.StringVar(value="127.0.0.1")
        self.connect_port_var = tk.StringVar(value="5001")

        self.message_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Stopped")

    def _build_style(self) -> None:
        style = ttk.Style(self)

        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("Title.TLabel", font=("Segoe UI", 14, "bold"))
        style.configure("Section.TLabelframe.Label", font=("Segoe UI", 9, "bold"))
        style.configure("Action.TButton", padding=(6, 3))

    def _build_ui(self) -> None:
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        canvas = tk.Canvas(self, highlightthickness=0)
        v_scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)

        outer = ttk.Frame(canvas, padding=10)

        def _on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        outer.bind("<Configure>", _on_frame_configure)

        canvas_window = canvas.create_window((0, 0), window=outer, anchor="nw")

        def _on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)

        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.configure(yscrollcommand=v_scrollbar.set)

        canvas.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")

        # Header Title
        ttk.Label(
            outer,
            text="Decentralized P2P Communication & File Sharing",
            style="Title.TLabel",
        ).pack(anchor="w", pady=(0, 6))

        # 1. My Peer Setup Frame
        setup = ttk.LabelFrame(
            outer, text="My Peer Setup", style="Section.TLabelframe", padding=6
        )
        setup.pack(fill="x", pady=(0, 6))

        ttk.Label(setup, text="Name:").pack(side="left", padx=(2, 4))
        ttk.Entry(setup, textvariable=self.name_var, width=15).pack(
            side="left", padx=(0, 10)
        )

        ttk.Label(setup, text="Port:").pack(side="left", padx=(2, 4))
        ttk.Entry(setup, textvariable=self.port_var, width=8).pack(
            side="left", padx=(0, 10)
        )

        self.start_button = ttk.Button(
            setup, text="Start Server", style="Action.TButton", command=self._start_node
        )
        self.start_button.pack(side="left", padx=4)

        self.stop_button = ttk.Button(
            setup, text="Stop Server", style="Action.TButton", command=self._stop_node
        )
        self.stop_button.pack(side="left", padx=4)

        ttk.Label(setup, textvariable=self.status_var).pack(side="left", padx=(10, 0))

        # 2. Connect to Peer Frame
        connection = ttk.LabelFrame(
            outer, text="Connect to Peer", style="Section.TLabelframe", padding=6
        )
        connection.pack(fill="x", pady=(0, 6))

        ttk.Label(connection, text="IP:").pack(side="left", padx=(2, 4))
        ttk.Entry(connection, textvariable=self.ip_var, width=15).pack(
            side="left", padx=(0, 10)
        )

        ttk.Label(connection, text="Port:").pack(side="left", padx=(2, 4))
        ttk.Entry(connection, textvariable=self.connect_port_var, width=8).pack(
            side="left", padx=(0, 10)
        )

        ttk.Button(
            connection, text="Connect", style="Action.TButton", command=self._connect
        ).pack(side="left", padx=4)

        # 3. Middle Section: Connected Peers & Chat Log
        middle_frame = ttk.Frame(outer, height=250)
        middle_frame.pack(fill="x", pady=(0, 6))
        middle_frame.pack_propagate(False)

        middle = ttk.Panedwindow(middle_frame, orient="horizontal")
        middle.pack(fill="both", expand=True)

        peers_frame = ttk.LabelFrame(
            middle, text="Connected Peers", style="Section.TLabelframe", padding=4
        )
        log_frame = ttk.LabelFrame(
            middle, text="Chat / Event Log", style="Section.TLabelframe", padding=4
        )

        middle.add(peers_frame, weight=1)
        middle.add(log_frame, weight=3)

        columns = ("peer_id", "name", "ip", "port")
        self.peer_tree = ttk.Treeview(
            peers_frame, columns=columns, show="headings", selectmode="browse"
        )

        headings = {"peer_id": "Peer ID", "name": "Name", "ip": "IP", "port": "Port"}
        widths = {"peer_id": 80, "name": 90, "ip": 90, "port": 50}

        for column in columns:
            self.peer_tree.heading(column, text=headings[column])
            self.peer_tree.column(
                column, width=widths[column], minwidth=40, anchor="center"
            )

        peer_scroll = ttk.Scrollbar(
            peers_frame, orient="vertical", command=self.peer_tree.yview
        )
        self.peer_tree.configure(yscrollcommand=peer_scroll.set)

        self.peer_tree.pack(side="left", fill="both", expand=True)
        peer_scroll.pack(side="right", fill="y")

        self.log_text = tk.Text(
            log_frame, wrap="word", state="disabled", font=("Consolas", 9)
        )
        log_scroll = ttk.Scrollbar(
            log_frame, orient="vertical", command=self.log_text.yview
        )
        self.log_text.configure(yscrollcommand=log_scroll.set)

        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

        # 4. Text Message Box Section
        message_frame = ttk.LabelFrame(
            outer, text="Text Message Input", style="Section.TLabelframe", padding=6
        )
        message_frame.pack(fill="x", pady=(0, 6))

        self.message_entry = ttk.Entry(message_frame, textvariable=self.message_var)
        self.message_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.message_entry.bind("<Return>", lambda _event: self._send_direct())

        ttk.Button(
            message_frame,
            text="Send (Direct)",
            style="Action.TButton",
            command=self._send_direct,
        ).pack(side="left", padx=2)

        # 5. File Transfer Section
        file_frame = ttk.LabelFrame(
            outer, text="File Transfer", style="Section.TLabelframe", padding=6
        )
        file_frame.pack(fill="x")

        ttk.Button(
            file_frame,
            text="Send File (Direct)",
            style="Action.TButton",
            command=self._send_file_direct,
        ).pack(side="left", padx=(0, 4))

        ttk.Label(file_frame, text="Saved automatically in ./downloads/").pack(
            side="right"
        )

    # ------------------------------------------------------------------
    # Node lifecycle & Operations
    # ------------------------------------------------------------------

    def _start_node(self) -> None:
        if self.node is not None:
            return

        try:
            name = self.name_var.get().strip() or "Peer"
            port = self._parse_port(self.port_var.get())

            node = P2PNode(
                name=name,
                port=port,
                event_callback=self._on_node_event,
                peers_callback=self._on_peers_changed,
            )
            node.start()

            self.node = node
            self.name_var.set(name)
            self.status_var.set(
                f"Running on {socket.gethostbyname(socket.gethostname())}:{port}"
            )
            self._set_running_state(True)

        except Exception as exc:
            messagebox.showerror("Start Failed", str(exc))

    def _stop_node(self) -> None:
        if self.node is None:
            return

        try:
            self.node.stop()
        finally:
            self.node = None
            self.status_var.set("Stopped")
            self._set_running_state(False)

    def _connect(self) -> None:
        if self.node is None:
            messagebox.showwarning(
                "Server Not Running", "Start your peer server before connecting."
            )
            return

        try:
            ip = self.ip_var.get().strip()
            port = self._parse_port(self.connect_port_var.get())

            socket.inet_pton(socket.AF_INET, ip)
            self.node.connect(ip, port)
        except OSError:
            messagebox.showerror("Invalid IP", "Please enter a valid IPv4 address.")
        except Exception as exc:
            messagebox.showerror("Connection Error", str(exc))

    def _selected_peer_id(self) -> str | None:
        selection = self.peer_tree.selection()
        if not selection:
            return None
        return str(selection[0])

    def _send_direct(self) -> None:
        node = self.node
        if node is None:
            messagebox.showwarning("Not Running", "Start the server first.")
            return

        peer_id = self._selected_peer_id()
        message = self.message_var.get().strip()

        if peer_id is None:
            messagebox.showwarning(
                "Select Peer", "Select a connected peer first from the list."
            )
            return

        if not message:
            messagebox.showwarning("Empty Message", "Enter a message first.")
            return

        try:
            node.send_text(peer_id, message)
            self.message_var.set("")
        except Exception as exc:
            messagebox.showerror("Send Failed", str(exc))

    def _select_file(self) -> str:
        return filedialog.askopenfilename(title="Select file to send")

    def _send_file_direct(self) -> None:
        node = self.node
        if node is None:
            messagebox.showwarning("Not Running", "Start the server first.")
            return

        peer_id = self._selected_peer_id()
        if peer_id is None:
            messagebox.showwarning("Select Peer", "Select a connected peer first.")
            return

        file_path = self._select_file()
        if not file_path:
            return

        try:
            node.send_file(peer_id, file_path)
        except Exception as exc:
            messagebox.showerror("File Send Failed", str(exc))

    def _on_node_event(self, message: str) -> None:
        self.after(0, self._append_log, message)

    def _on_peers_changed(self, peers: list[dict[str, Any]]) -> None:
        self.after(0, self._refresh_peer_tree, peers)

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _refresh_peer_tree(self, peers: list[dict[str, Any]]) -> None:
        for item in self.peer_tree.get_children():
            self.peer_tree.delete(item)

        for peer in sorted(peers, key=lambda item: item["name"].lower()):
            self.peer_tree.insert(
                "",
                "end",
                iid=peer["peer_id"],
                values=(
                    peer["peer_id"][:8],
                    peer["name"],
                    peer["ip"],
                    peer["port"],
                ),
            )

    @staticmethod
    def _parse_port(value: str) -> int:
        try:
            port = int(value.strip())
        except ValueError as exc:
            raise ValueError("Port must be a number.") from exc

        if not 1 <= port <= 65535:
            raise ValueError("Port must be between 1 and 65535.")

        return port

    def _set_running_state(self, running: bool) -> None:
        self.start_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")

    def _on_close(self) -> None:
        try:
            self._stop_node()
        finally:
            self.destroy()


def main() -> None:
    app = P2PApplication()
    app.mainloop()


if __name__ == "__main__":
    main()