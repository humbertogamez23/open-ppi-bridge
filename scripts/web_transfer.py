#!/usr/bin/env python3
"""
scripts/web_transfer.py - Servidor local de transferencia de archivos entre VM (Windows 7) y Host (Linux).
open-ppi-bridge - Proyecto SIMATIC S7-200

Permite descargar e intercambiar programas de PLC (.awl, .mwp, .bin)
desde el navegador web de Windows 7 (http://10.0.2.2:8000) directamente
con la carpeta compartida del host en Linux.
Compatible con Python 3.8 a 3.14+ (sin módulo obsoleto cgi).
"""

import os
import sys
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from email import message_from_bytes

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SHARED_DIR = os.path.join(REPO_ROOT, "vm", "shared")
DEFAULT_PORT = 8000

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>open-ppi-bridge | Transferencia PLC (VM &harr; Host)</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
            background: #0f172a;
            color: #f1f5f9;
            margin: 0;
            padding: 30px;
        }}
        .card {{
            max-width: 720px;
            margin: 0 auto;
            background: #1e293b;
            border-radius: 12px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.4);
            padding: 30px;
            border: 1px solid #334155;
        }}
        h1 {{
            color: #38bdf8;
            margin-top: 0;
            font-size: 24px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        p {{
            color: #94a3b8;
            font-size: 15px;
            line-height: 1.5;
        }}
        .dropzone {{
            border: 2px dashed #38bdf8;
            border-radius: 8px;
            padding: 25px;
            text-align: center;
            background: #0f172a;
            margin: 20px 0;
        }}
        input[type="file"] {{
            margin: 15px 0;
            color: #94a3b8;
        }}
        button {{
            background: #0284c7;
            color: white;
            border: none;
            padding: 12px 24px;
            font-size: 15px;
            font-weight: bold;
            border-radius: 6px;
            cursor: pointer;
            transition: background 0.2s;
        }}
        button:hover {{
            background: #0369a1;
        }}
        .list {{
            margin-top: 25px;
            border-top: 1px solid #334155;
            padding-top: 20px;
        }}
        .file-item {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 14px;
            background: #0f172a;
            border-radius: 6px;
            margin-bottom: 8px;
            font-family: "Courier New", Courier, monospace;
            border: 1px solid #334155;
        }}
        .file-link {{
            text-decoration: none;
            color: #38bdf8;
            font-weight: bold;
        }}
        .file-link:hover {{
            text-decoration: underline;
        }}
        .badge {{
            background: #334155;
            color: #e2e8f0;
            padding: 3px 10px;
            border-radius: 4px;
            font-size: 12px;
        }}
        .footer {{
            margin-top: 20px;
            font-size: 12px;
            color: #64748b;
            text-align: center;
        }}
    </style>
</head>
<body>
<div class="card">
    <h1>📤 open-ppi-bridge &bull; Transferencia de Archivos</h1>
    <p>Intercambio rápido entre la máquina virtual (Micro/WIN) y el host (Linux).
       Guarda tu proyecto (<strong>.mwp</strong>) o exporta a código AWL (<strong>Archivo &rarr; Exportar &rarr; .awl</strong>) y súbelo aquí.</p>
    
    <form method="POST" enctype="multipart/form-data">
        <div class="dropzone">
            <strong>Selecciona o arrastra tu archivo (.awl, .mwp, .bin):</strong><br><br>
            <input type="file" name="file" required><br>
            <button type="submit">Subir a Linux 🚀</button>
        </div>
    </form>

    <div class="list">
        <h3>📁 Archivos disponibles para descargar en Windows:</h3>
        {file_list}
    </div>

    <div class="footer">
        open-ppi-bridge &bull; Servidor HTTP en puerto {port} &bull; Carpeta: {shared_dir}
    </div>
</div>
</body>
</html>
"""

class TransferHandler(BaseHTTPRequestHandler):
    shared_dir = DEFAULT_SHARED_DIR
    port = DEFAULT_PORT

    def log_message(self, format, *args):
        # Silenciar logs ruidosos de polling
        sys.stderr.write(f"[HTTP {self.log_date_time_string()}] {format % args}\n")

    def do_GET(self):
        if self.path.startswith('/download/'):
            filename = os.path.basename(self.path[10:])
            file_path = os.path.join(self.shared_dir, filename)
            if os.path.isfile(file_path):
                try:
                    with open(file_path, 'rb') as f:
                        data = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                except Exception as e:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(f"Error leyendo archivo: {e}".encode("utf-8"))
                    return
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Archivo no encontrado")
                return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        files = os.listdir(self.shared_dir) if os.path.exists(self.shared_dir) else []
        if files:
            items = []
            for f in sorted(files):
                full_p = os.path.join(self.shared_dir, f)
                if os.path.isfile(full_p):
                    size = os.path.getsize(full_p)
                    items.append(
                        f'<div class="file-item">'
                        f'<span><a class="file-link" href="/download/{f}">⬇️ {f}</a></span>'
                        f'<span class="badge">{size:,} bytes</span>'
                        f'</div>'
                    )
            file_list_html = "".join(items) if items else "<em>(No hay archivos en la carpeta compartida)</em>"
        else:
            file_list_html = "<em>(Carpeta compartida vacía)</em>"

        html = HTML_TEMPLATE.format(
            file_list=file_list_html,
            port=self.port,
            shared_dir=os.path.basename(self.shared_dir)
        )
        self.wfile.write(html.encode("utf-8"))

    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)

            msg_data = b'Content-Type: ' + self.headers.get('Content-Type', '').encode('latin1') + b'\r\n\r\n' + body
            msg = message_from_bytes(msg_data)

            uploaded_count = 0
            for part in msg.walk():
                fn = part.get_filename()
                if fn:
                    clean_name = os.path.basename(fn)
                    payload = part.get_payload(decode=True)
                    if payload is not None:
                        out_path = os.path.join(self.shared_dir, clean_name)
                        with open(out_path, 'wb') as f:
                            f.write(payload)
                        uploaded_count += 1
                        print(f"[*] Archivo subido con éxito: {clean_name} ({len(payload)} bytes)")

            self.send_response(303)
            self.send_header('Location', '/')
            self.end_headers()
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"Error procesando archivo: {e}".encode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Servidor local HTTP de intercambio de archivos PLC")
    parser.add_argument("--dir", default=DEFAULT_SHARED_DIR, help="Directorio compartido (host)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Puerto HTTP (por defecto: 8000)")
    args = parser.parse_args()

    os.makedirs(args.dir, exist_ok=True)
    TransferHandler.shared_dir = os.path.abspath(args.dir)
    TransferHandler.port = args.port

    server = HTTPServer(('0.0.0.0', args.port), TransferHandler)
    print(f"[*] Servidor de transferencia web activo en http://0.0.0.0:{args.port}")
    print(f"[*] Carpeta compartida: {TransferHandler.shared_dir}")
    print(f"[*] Desde Windows 7 ingresa con el navegador a: http://10.0.2.2:{args.port}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Deteniendo servidor de transferencia...")
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
