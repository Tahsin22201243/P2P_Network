# CSE 433 - Decentralized P2P Communication & File Sharing

## 1. Project Information

A fully decentralized peer-to-peer communication and file-sharing application implemented in Python using:

- TCP sockets
- Python `threading`
- Tkinter
- JSON
- 4-byte big-endian length-prefix framing
- 64 KiB file chunks

There is **no central server**. Every running application instance is both:

1. a TCP server that accepts incoming peer connections; and
2. a TCP client that can connect to another peer.

### Important implementation detail

TCP is a byte stream rather than a message protocol. Therefore the project uses:

```text
[4-byte big-endian JSON length][JSON bytes]
```

For a file transfer, the sequence is:

```text
[4-byte length][file metadata JSON][exactly file_size raw bytes]
```

The receiver reads exactly `file_size` bytes after receiving the metadata. The raw file bytes are never passed through JSON and are never mixed with another message.

Each peer connection also has a dedicated `send_lock`. This is essential because a file transfer consists of a metadata frame followed immediately by raw bytes. Without serialization, another thread could insert a message into the middle of the file stream and corrupt the protocol.

---

## 2. Directory Structure

```text
p2p_cse433/
├── main.py
├── p2p_node.py
├── protocol.py
├── requirements.txt
├── README.md
└── downloads/
    └── (received files are created here automatically)
```

The `downloads/` directory is automatically created by `P2PNode` when the application starts.

---

## 3. Requirements

Python 3.9 or newer is recommended.

The implementation uses only Python standard-library modules:

- socket
- threading
- json
- struct
- os
- pathlib
- hashlib
- uuid
- tkinter

No third-party Python package is required.

### Linux Tkinter note

On some Linux distributions, Tkinter is distributed separately from Python. Install the distribution's Tk package if:

```bash
python3 -m tkinter
```

does not open a small test window.

---

## 4. Installation

Create and enter the project directory:

```bash
cd p2p_cse433
```

Optional virtual environment:

### Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Linux/macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the requirements file:

```bash
python -m pip install -r requirements.txt
```

Because the project is standard-library only, pip has nothing external to install.

---

## 5. Run One Peer

```bash
python main.py
```

Enter:

```text
Name: Peer 1
Port: 5000
```

Click **Start Server**.

The server listens on:

```text
0.0.0.0:5000
```

---

## 6. Same-Machine Testing with Three Peers

Open three terminals.

### Terminal 1

```bash
python main.py
```

Use:

```text
Name: Peer 1
Port: 5000
```

### Terminal 2

```bash
python main.py
```

Use:

```text
Name: Peer 2
Port: 5001
```

### Terminal 3

```bash
python main.py
```

Use:

```text
Name: Peer 3
Port: 5002
```

From Peer 1:

```text
IP: 127.0.0.1
Port: 5001
```

Click **Connect**.

Then connect Peer 1 to:

```text
127.0.0.1:5002
```

You can also create a chain:

```text
Peer 1 <-> Peer 2 <-> Peer 3
```

For a demonstration of "all connected peers", connect Peer 1 directly to Peer 2 and Peer 3.

---

## 7. Testing on Multiple Machines

Suppose:

```text
Machine A: 192.168.1.10
Machine B: 192.168.1.11
```

On Machine A:

```text
Name: Peer A
Port: 5000
```

On Machine B:

```text
Name: Peer B
Port: 5001
```

Start both servers.

From Machine B connect to:

```text
IP: 192.168.1.10
Port: 5000
```

Make sure the operating-system firewall permits inbound TCP traffic on the selected port and that both machines can reach one another on the network.

Do not use `127.0.0.1` between different machines. Loopback refers to the local machine only.

---

# 8. Application Features

## 8.1 Peer setup

Each node has:

- peer name
- TCP listening port
- randomly generated UUID peer ID

Example:

```text
Peer ID: 0a4d9d2e-...
Name: Peer 1
Port: 5000
```

The peer ID is generated locally and is not assigned by a central server.

## 8.2 Incoming connections

The listener runs in a daemon thread.

The main Tkinter GUI is never used as the TCP accept loop.

## 8.3 Outgoing connections

Every connection attempt runs in its own worker thread.

This prevents a slow or unreachable peer from freezing the GUI.

## 8.4 Per-peer receiving

Every accepted/connected socket has a receive thread.

That thread continuously:

1. reads one framed JSON message;
2. determines the message type;
3. dispatches the message;
4. for file metadata, reads exactly the advertised file byte count.

## 8.5 Text messaging

Direct messages use:

```json
{
  "type": "text",
  "sender_id": "...",
  "sender_name": "...",
  "message": "Hello"
}
```

## 8.7 File transfer

File metadata is sent first:

```json
{
  "type": "file_meta",
  "sender_id": "...",
  "sender_name": "...",
  "filename": "example.pdf",
  "file_size": 123456,
  "transfer_id": "...",
  "sha256": "..."
}
```

Then the sender sends raw bytes:

```text
64 KiB
64 KiB
64 KiB
...
remaining bytes
```

The receiver creates:

```text
downloads/
```

if it does not exist.

It first writes to a temporary `.part` file. Once all bytes have been received and the SHA-256 checksum matches, the temporary file is atomically renamed to its final name.

If a file with the same name already exists, the receiver creates names such as:

```text
report (1).pdf
report (2).pdf
```

This prevents accidental overwriting.


---

# 9. Protocol Design

## 9.1 Why framing is necessary

TCP does not preserve application message boundaries.

One call to:

```python
sendall()
```

does not guarantee that one corresponding:

```python
recv()
```

returns exactly the same application message.

Therefore the application adds a 4-byte length field.

For example:

```text
00 00 00 35
```

could mean that the JSON payload is 53 bytes long.

The receiver first reads exactly four bytes:

```python
header = recv_exact(sock, 4)
```

then converts them:

```python
length = struct.unpack("!I", header)[0]
```

and finally reads exactly `length` bytes.

The `!I` format means:

- `!` = network/big-endian byte order
- `I` = unsigned 4-byte integer

---

# 10. File Stream Synchronization

This is the most important protocol-safety rule in the project.

The sender must send:

```text
JSON file metadata
RAW FILE DATA
```

as one serialized operation for a given connection.

Therefore `PeerConnection.send_file()` uses:

```python
with self.send_lock:
    send_framed_message(...)
    send raw chunks
```

A different message cannot enter the socket until the complete file transfer is finished.

On the receiving side:

```text
recv framed metadata
        |
        v
read exactly file_size bytes
        |
        v
verify SHA-256
        |
        v
continue reading next framed message
```

This keeps the stream synchronized.

---

# 11. Thread Safety

The application uses several synchronization mechanisms.

## `peers_lock`

Protects the shared peer dictionary:

```python
self.peers
```

Multiple networking threads can add/remove/read peers.

## `send_lock`

Every peer connection has its own:

```python
send_lock
```

This serializes outgoing messages and file streams on that socket.

## Tkinter thread rule

Tkinter widgets should only be manipulated from the Tkinter main thread.

Network worker threads therefore call:

```python
root.after(0, callback)
```

before updating the GUI.

This prevents common Tkinter cross-thread crashes.

---

# 12. Fault Tolerance

The implementation handles:

- invalid ports
- invalid IPv4 addresses
- refused connections
- unreachable peers
- connection resets
- peer disconnects
- listener shutdown
- invalid JSON
- oversized JSON frames
- malformed handshake messages
- invalid file metadata
- invalid file names
- checksum mismatch
- partial file transfers
- duplicate peer connections
- application shutdown

Sockets use timeouts so worker threads periodically regain control and shutdown can happen cleanly.

All networking threads are daemon threads.

---

# 13. Graceful Shutdown

When the GUI closes:

1. the node stops accepting new connections;
2. the listening socket is closed;
3. all peer sockets are closed;
4. the peer dictionary is cleared;
5. the Tkinter application exits.

No central server has to be notified.

---

# 14. Security / Robustness Notes

This is an educational CSE 433 assignment implementation, not an Internet-facing secure messenger.

It does **not** provide:

- TLS encryption
- peer authentication
- cryptographic identity verification
- end-to-end encryption
- access control
- NAT traversal
- relay servers
- malicious-peer sandboxing

The SHA-256 value is used for file-integrity verification, not authentication.

A production Internet deployment should use TLS or another authenticated secure transport and stronger peer authentication.

---

# 15. Viva / Demonstration Questions and Answers

The exact assignment PDF containing the requested 20 viva questions was not available in the project files I could access. The following 20 questions are therefore tailored to this implementation rather than claimed to be the PDF's exact wording.

## Q1. What architecture does this project use?

It uses a fully decentralized peer-to-peer architecture. Every node acts both as a TCP server and a TCP client. There is no central coordination server.

## Q2. Why does every peer need a server socket?

A peer must be able to accept incoming TCP connections from other peers. Therefore each running application listens on its own TCP port.

## Q3. Why does every peer also need client functionality?

A peer must be able to initiate a connection to another peer. The client side creates a TCP socket and calls `connect()`.

## Q4. Why is message framing required over TCP?

TCP is a byte-stream protocol and does not preserve application message boundaries. A receiver may receive multiple messages together or one message in multiple pieces. Length-prefix framing solves this problem.

## Q5. What does the 4-byte prefix contain?

It contains the number of bytes in the following UTF-8 encoded JSON payload. It is encoded using big-endian unsigned 32-bit format.

## Q6. Why use `recv_exact()`?

A normal `recv()` call may return fewer bytes than requested. `recv_exact()` repeatedly receives data until the requested number of bytes has arrived or the connection is closed.

## Q7. How is the handshake performed?

The local peer sends a `hello` containing its `peer_id`, `peer_name`, and listening `port`. It receives a `hello` or `hello_ack`, validates the remote identity, and sends a `hello_ack`.

## Q8. What is the purpose of `peer_id`?

The peer ID uniquely identifies a node independently of its IP address or display name. It is generated locally as a UUID.

## Q9. How is a direct text message sent?

The GUI selects one peer, then `send_text()` creates a `text` JSON payload and sends it through that peer's TCP socket.


## Q12. How is binary file data transmitted?

First a framed JSON file metadata message is sent. Immediately after it, the raw file bytes are transmitted in 64 KiB chunks.

## Q13. Why are file bytes not encoded as JSON?

Binary data is larger and less efficient when converted to JSON/base64. Sending raw bytes also directly satisfies the binary file transfer requirement.

## Q14. How does the receiver know where the file ends?

The metadata contains `file_size`. The receiver reads exactly that many raw bytes before returning to the normal framed-message receive loop.

## Q15. Why is a `send_lock` necessary?

Multiple worker threads may try to send through the same TCP socket. A file transfer consists of metadata followed by raw bytes, so another thread inserting data in the middle would corrupt the stream. The lock makes the whole transfer atomic with respect to other sends on that connection.

## Q16. Why are separate threads used?

Network operations can block. Separate threads prevent one slow connection or file transfer from freezing the GUI or other peer connections.

## Q17. How is the GUI kept thread-safe?

Networking callbacks do not directly modify Tkinter widgets. They schedule GUI updates using Tkinter's `after()` method so updates execute on the main GUI thread.

## Q18. How are received files protected from partial transfers?

The receiver writes to a temporary `.part` file. After exactly the advertised number of bytes arrive and the SHA-256 checksum matches, the temporary file is renamed to the final filename.

## Q19. What happens if a peer disconnects?

The receive/send operation raises a connection-related exception. The node closes the socket, removes that peer from the shared peer dictionary, updates the GUI, and continues serving other peers.

## Q20. What would you add for a real production Internet deployment?

I would add TLS, authenticated peer identities, authorization, rate limiting, maximum file-size limits, NAT traversal or a rendezvous mechanism, resumable transfers, persistent peer discovery, stronger protocol versioning, structured telemetry, and comprehensive automated tests.

---

# 16. Demonstration Sequence

For a classroom demonstration:

### Step 1

Run three copies:

```text
Peer 1 -> 5000
Peer 2 -> 5001
Peer 3 -> 5002
```

### Step 2

Connect Peer 1 to Peer 2 and Peer 3.

### Step 3

Show the Connected Peers table.

### Step 4

Send a direct message from Peer 1 to Peer 2.


### Step 6

Select a small text/PDF/image file.

Send it directly to Peer 2.

The receiver should show a new file inside:

```text
downloads/
```


### Step 8

Stop Peer 2.

The other node should remove the disconnected peer without crashing.

### Step 9

Restart Peer 2 and reconnect it.

This demonstrates recovery from a peer disconnect.

---

# 17. Suggested Test Cases

| Test | Expected Result |
|---|---|
| Invalid port `abc` | GUI reports invalid port |
| Port `70000` | GUI reports invalid port |
| Invalid IP | GUI reports invalid IPv4 |
| Connect to unused port | Connection fails without GUI freeze |
| Direct text | Selected peer receives text |
| Small file | File appears in `downloads/` |
| Large file | File transfers in 64 KiB chunks |
| Duplicate filename | Existing file is not overwritten |
| Checksum mismatch | Temporary file is discarded |
| Peer disconnect | Peer disappears from list |
| Stop server | Listener and peer sockets close |
| GUI close | Node shuts down cleanly |

---

# 18. Running the Source

The complete application consists of:

```bash
python main.py
```

No separate server command exists because every application instance is simultaneously a server and a client.

