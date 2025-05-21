import socket
import threading
import json
import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox
from PIL import Image, ImageTk, ImageDraw
import io
import base64
import os
import logging
import cv2
import pickle
import struct
import numpy as np

logging.basicConfig(level=logging.DEBUG)


class VideoCall:
    def __init__(self, host, port, on_frame_received):
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.host_ip = host
        self.port = port
        self.is_running = False
        self.frame_count = 0
        self.on_frame_received = on_frame_received

    def start(self):
        try:
            self.client_socket.connect((self.host_ip, self.port))
            self.is_running = True
            threading.Thread(target=self.receive_video, daemon=True).start()
            threading.Thread(target=self.send_video, daemon=True).start()
        except ConnectionRefusedError:
            raise Exception(
                "No se pudo conectar al servidor de video. Asegúrate de que el servidor esté en funcionamiento.")
        except Exception as e:
            raise Exception(f"Error al iniciar la videollamada: {str(e)}")

    def receive_video(self):
        data = b""
        payload_size = struct.calcsize("Q")
        while self.is_running:
            try:
                while len(data) < payload_size:
                    packet = self.client_socket.recv(4 * 1024)
                    if not packet:
                        break
                    data += packet
                packed_msg_size = data[:payload_size]
                data = data[payload_size:]
                msg_size = struct.unpack("Q", packed_msg_size)[0]
                while len(data) < msg_size:
                    data += self.client_socket.recv(4 * 1024)
                frame_data = data[:msg_size]
                data = data[msg_size:]
                frame = pickle.loads(frame_data)

                self.frame_count += 1
                if self.frame_count % 30 == 0:
                    logging.info(f"Recibido frame {self.frame_count}")

                self.on_frame_received(frame)
            except Exception as e:
                logging.error(f"Error en la recepción de video: {str(e)}")
                break

    def send_video(self):
        cap = cv2.VideoCapture(0)
        while self.is_running:
            ret, frame = cap.read()
            if ret:
                data = pickle.dumps(frame)
                message_size = struct.pack("Q", len(data))
                try:
                    self.client_socket.sendall(message_size + data)
                except Exception as e:
                    logging.error(f"Error al enviar video: {str(e)}")
                    break
        cap.release()

    def stop(self):
        self.is_running = False
        self.client_socket.close()


class ChatClient:
    def __init__(self, host='localhost', port=14999):
        self.host = host
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.username = None
        self.current_chat = None
        self.users = []
        self.groups = {}
        self.profile_images = {}
        self.received_files_dir = "received_files"
        os.makedirs(self.received_files_dir, exist_ok=True)

        self.root = tk.Tk()
        self.root.title("ChatApp")
        self.root.geometry("1200x600")

        self.video_call = None
        self.video_server_host = 'localhost'
        self.video_server_port = 14999
        self.setup_ui()

    def setup_ui(self):
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=3)
        self.root.grid_columnconfigure(2, weight=2)
        self.root.grid_rowconfigure(0, weight=1)

        self.users_frame = ttk.Frame(self.root)
        self.users_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.users_frame.grid_rowconfigure(0, weight=1)
        self.users_frame.grid_columnconfigure(0, weight=1)

        self.users_tree = ttk.Treeview(self.users_frame, columns=('image',), show='tree', height=20)
        self.users_tree.grid(row=0, column=0, sticky="nsew")
        self.users_tree.bind("<<TreeviewSelect>>", self.on_user_select)

        self.users_scrollbar = ttk.Scrollbar(self.users_frame, orient="vertical", command=self.users_tree.yview)
        self.users_scrollbar.grid(row=0, column=1, sticky="ns")
        self.users_tree.configure(yscrollcommand=self.users_scrollbar.set)

        style = ttk.Style()
        style.configure("Treeview", rowheight=80)

        self.button_frame = ttk.Frame(self.users_frame)
        self.button_frame.grid(row=1, column=0, columnspan=2, pady=5)

        self.create_group_button = ttk.Button(self.button_frame, text="Crear Grupo", command=self.create_group)
        self.create_group_button.pack(side=tk.LEFT, padx=5)

        self.profile_image_button = ttk.Button(self.button_frame, text="Cambiar Imagen",
                                               command=self.select_profile_image)
        self.profile_image_button.pack(side=tk.LEFT, padx=5)

        self.chat_frame = ttk.Frame(self.root)
        self.chat_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        self.chat_frame.grid_columnconfigure(0, weight=1)
        self.chat_frame.grid_rowconfigure(1, weight=1)

        self.chat_info = ttk.Label(self.chat_frame, text="Chat")
        self.chat_info.grid(row=0, column=0, sticky="w", padx=5, pady=5)

        self.message_area = tk.Text(self.chat_frame, state='disabled')
        self.message_area.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

        self.input_frame = ttk.Frame(self.chat_frame)
        self.input_frame.grid(row=2, column=0, sticky="ew", padx=5, pady=5)
        self.input_frame.grid_columnconfigure(0, weight=1)

        self.message_input = ttk.Entry(self.input_frame)
        self.message_input.grid(row=0, column=0, sticky="ew", padx=5)

        self.send_button = ttk.Button(self.input_frame, text="Enviar", command=self.send_message)
        self.send_button.grid(row=0, column=1, padx=5)

        self.file_button = ttk.Button(self.input_frame, text="Adjuntar", command=self.send_file)
        self.file_button.grid(row=0, column=2, padx=5)

        self.emoji_button = ttk.Button(self.input_frame, text="Emojis", command=self.show_emoji_menu)
        self.emoji_button.grid(row=0, column=3, padx=5)

        self.video_call_button = ttk.Button(self.input_frame, text="Video llamada", command=self.toggle_video_call)
        self.video_call_button.grid(row=0, column=4, padx=5)

        self.emoji_button.grid(row=0, column=5, padx=5)

        self.local_video_frame = ttk.Frame(self.root)
        self.local_video_frame.grid(row=0, column=2, sticky="nsew", padx=5, pady=5)
        self.local_video_label = ttk.Label(self.local_video_frame)
        self.local_video_label.pack()

        self.remote_video_frame = ttk.Frame(self.root)
        self.remote_video_frame.grid(row=1, column=2, sticky="nsew", padx=5, pady=5)
        self.remote_video_label = ttk.Label(self.remote_video_frame)
        self.remote_video_label.pack()

    def toggle_video_call(self):
        if self.video_call is None or not self.video_call.is_running:
            self.start_video_call()
        else:
            self.stop_video_call()

    def start_video_call(self):
        if self.current_chat and self.current_chat not in self.groups:
            self.video_call = VideoCall(self.video_server_host, self.video_server_port, self.on_remote_frame_received)
            try:
                self.video_call.start()
                self.video_call_button.config(text="Terminar Video")
                self.display_message("ChatApp", "Videollamada iniciada.")

                # Enviar notificación al servidor
                data = {
                    'type': 'start_video_call',
                    'recipient': self.current_chat
                }
                self.socket.sendall(json.dumps(data).encode('utf-8') + b'\n')

                self.start_local_video()
            except Exception as e:
                error_message = str(e)
                self.display_message("ChatApp", f"Error al iniciar la videollamada: {error_message}")
                self.video_call = None

                response = messagebox.askyesno("Error de Conexión",
                                               "No se pudo conectar al servidor de video. ¿Deseas intentar configurar manualmente la dirección del servidor?")
                if response:
                    self.configure_video_server()
        else:
            self.display_message("ChatApp", "Selecciona un usuario para iniciar la videollamada.")

    def start_local_video(self):
        def show_local_video():
            cap = cv2.VideoCapture(0)
            while self.video_call and self.video_call.is_running:
                ret, frame = cap.read()
                if ret:
                    self.display_video_frame(frame, self.local_video_label)
            cap.release()

        threading.Thread(target=show_local_video, daemon=True).start()

    def on_remote_frame_received(self, frame):
        self.display_video_frame(frame, self.remote_video_label)

    def display_video_frame(self, frame, label):
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(frame)
        image = image.resize((320, 240), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(image=image)
        label.config(image=photo)
        label.image = photo
        self.root.update_idletasks()

    def stop_video_call(self):
        if self.video_call:
            self.video_call.stop()
            self.video_call = None
            self.video_call_button.config(text="Video llamada")
            self.display_message("ChatApp", "Videollamada terminada.")
            self.local_video_label.config(image='')
            self.remote_video_label.config(image='')

    def configure_video_server(self):
        config_window = tk.Toplevel(self.root)
        config_window.title("Configuración del Servidor de Video")

        ttk.Label(config_window, text="Dirección IP del servidor:").grid(row=0, column=0, padx=5, pady=5)
        ip_entry = ttk.Entry(config_window)
        ip_entry.insert(0, self.video_server_host)
        ip_entry.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(config_window, text="Puerto del servidor:").grid(row=1, column=0, padx=5, pady=5)
        port_entry = ttk.Entry(config_window)
        port_entry.insert(0, str(self.video_server_port))
        port_entry.grid(row=1, column=1, padx=5, pady=5)

        def save_config():
            new_host = ip_entry.get()
            new_port = port_entry.get()

            try:
                new_port = int(new_port)
                if new_port < 1 or new_port > 65535:
                    raise ValueError("Puerto fuera de rango")

                self.video_server_host = new_host
                self.video_server_port = new_port
                self.display_message("ChatApp",
                                     f"Configuración del servidor de video actualizada a {new_host}:{new_port}")
                config_window.destroy()
            except ValueError:
                messagebox.showerror("Error", "Por favor, ingresa un número de puerto válido (1-65535)")

        ttk.Button(config_window, text="Guardar", command=save_config).grid(row=2, column=0, columnspan=2, pady=10)

    def test_video_server_connection(self):
        try:
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_socket.settimeout(5)
            test_socket.connect((self.video_server_host, self.video_server_port))
            test_socket.close()
            messagebox.showinfo("Prueba de Conexión", "Conexión exitosa al servidor de video.")
        except Exception as e:
            messagebox.showerror("Error de Conexión", f"No se pudo conectar al servidor de video: {str(e)}")

    def connect(self):
        try:
            self.socket.connect((self.host, self.port))
            self.username = simpledialog.askstring("Nombre de usuario", "Ingrese su nombre de usuario:",
                                                   parent=self.root)
            if not self.username:
                self.root.quit()
                return
            self.root.title(f"ChatApp - {self.username}")
            self.socket.send(self.username.encode('utf-8'))

            default_image = Image.new('RGB', (160, 160), color='gray')
            buffered = io.BytesIO()
            default_image.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode('utf-8')
            self.socket.send(img_str.encode('utf-8'))

            threading.Thread(target=self.receive_messages, daemon=True).start()
            self.root.mainloop()
        except Exception as e:
            logging.error(f"Error de conexión: {e}")

    def receive_messages(self):
        buffer = b""
        while True:
            try:
                chunk = self.socket.recv(4096)
                if not chunk:
                    raise ConnectionError("Desconectado del servidor.")

                buffer += chunk
                while b'\n' in buffer:
                    message, buffer = buffer.split(b'\n', 1)
                    try:
                        data = json.loads(message.decode('utf-8'))
                        self.process_message(data)
                    except json.JSONDecodeError:
                        logging.warning("Mensaje no JSON recibido, posiblemente un archivo.")
                        self.process_file_chunk(message)
            except (ConnectionError, OSError) as e:
                logging.error(f"Error de conexión: {e}")
                break

    def process_message(self, data):
        if data['type'] == 'user_list':
            self.update_user_list(data['users'])
        elif data['type'] == 'message':
            if data['content'].startswith("[Archivo recibido:"):
                self.handle_received_file(data['sender'], data['content'])
            else:
                self.display_message(data['sender'], data['content'])
        elif data['type'] == 'group_message':
            self.display_message(f"{data['sender']} (en {data['group']})", data['content'])
        elif data['type'] == 'group_created':
            self.add_group(data['group_name'], data['members'])
        elif data['type'] == 'start_video_call':
            self.start_video_call()

    def handle_received_file(self, sender, message):
        file_info, file_path = message.split(". Guardado en: ")
        self.display_message(sender, f"{file_info}\nUbicación en el servidor: {file_path}")

    def send_message(self):
        message = self.message_input.get()
        if message and self.current_chat:
            data = {
                'type': 'message',
                'recipient': self.current_chat,
                'content': message
            }
            try:
                self.socket.sendall(json.dumps(data).encode('utf-8') + b'\n')
                self.display_message("Tú", message)
                self.message_input.delete(0, tk.END)
            except Exception as e:
                logging.error(f"Error al enviar el mensaje: {e}")
        elif not self.current_chat:
            self.display_message("ChatApp", "Por favor, selecciona un destinatario antes de enviar un mensaje.")

    def send_file(self):
        if not self.current_chat:
            self.display_message("ChatApp", "Por favor, selecciona un destinatario antes de enviar un archivo.")
            return

        file_path = filedialog.askopenfilename()
        if file_path:
            file_size = os.path.getsize(file_path)
            chunk_size = 1024 * 1024

            try:
                with open(file_path, 'rb') as file:
                    chunk_number = 0
                    while True:
                        chunk = file.read(chunk_size)
                        if not chunk:
                            break

                        encoded_chunk = base64.b64encode(chunk).decode('utf-8')
                        data = {
                            'type': 'file_chunk',
                            'recipient': self.current_chat,
                            'file_name': file_path.split('/')[-1],
                            'chunk_number': chunk_number,
                            'total_chunks': (file_size - 1) // chunk_size + 1,
                            'content': encoded_chunk
                        }
                        message = json.dumps(data) + '\n'
                        self.socket.sendall(message.encode('utf-8'))
                        chunk_number += 1

                self.display_message("Tú", f"[Archivo enviado: {file_path.split('/')[-1]}]")
            except Exception as e:
                logging.error(f"Error al enviar el archivo: {e}")

    def process_file_chunk(self, chunk):
        logging.info(f"Chunk de archivo recibido: {chunk[:50]}...")

    def display_message(self, sender, content):
        self.message_area.config(state='normal')
        self.message_area.insert(tk.END, f"{sender}: {content}\n")
        self.message_area.config(state='disabled')
        self.message_area.see(tk.END)

    def select_profile_image(self):
        file_path = filedialog.askopenfilename(filetypes=[("Image files", "*.png *.jpg *.jpeg *.gif")])
        if file_path:
            try:
                with open(file_path, 'rb') as file:
                    img_data = file.read()
                img_str = base64.b64encode(img_data).decode('utf-8')
                data = {
                    'type': 'profile_image',
                    'image': img_str
                }
                self.socket.sendall(json.dumps(data).encode('utf-8') + b'\n')
                logging.info(f"Imagen de perfil enviada: {file_path}")

                image = Image.open(file_path)
                image = image.resize((60, 60), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(image)
                self.profile_images[self.username] = photo

                self.update_user_list(self.users)
            except Exception as e:
                logging.error(f"Error al enviar la imagen de perfil: {e}")

    def show_emoji_menu(self):
        emoji_window = tk.Toplevel(self.root)
        emoji_window.title("Emojis")
        emojis = ["😊", "😂", "❤️", "👍", "🎉"]
        for emoji in emojis:
            button = ttk.Button(emoji_window, text=emoji, command=lambda e=emoji: self.insert_emoji(e))
            button.pack(side=tk.LEFT, padx=5, pady=5)

    def insert_emoji(self, emoji):
        self.message_input.insert(tk.END, emoji)

    def update_user_list(self, users):
        self.users = users
        self.users_tree.delete(*self.users_tree.get_children())
        for user in users:
            if user['username'] != self.username:
                image = self.get_profile_image(user['username'], user['profile_image'])
                self.users_tree.insert('', 'end', text=user['username'], image=image)
        for group in self.groups:
            self.users_tree.insert('', 'end', text=group, tags=('group',))

    def get_profile_image(self, username, image_str):
        if username == self.username and username in self.profile_images:
            return self.profile_images[username]
        if image_str:
            try:
                image_data = base64.b64decode(image_str)
                image = Image.open(io.BytesIO(image_data))
                image = image.resize((60, 60), Image.Resampling.LANCZOS)
                mask = Image.new('L', (60, 60), 0)
                draw = ImageDraw.Draw(mask)
                draw.ellipse((0, 0, 60, 60), fill=255)
                output = ImageTk.PhotoImage(Image.composite(image, Image.new('RGB', (60, 60), (0, 0, 0)), mask))
                self.profile_images[username] = output
                return output
            except Exception as e:
                logging.error(f"Error al procesar la imagen de perfil de {username}: {e}")
        return None

    def on_user_select(self, event):
        selection = self.users_tree.selection()
        if selection:
            selected_item = selection[0]
            self.current_chat = self.users_tree.item(selected_item, "text")
            if self.current_chat in self.groups:
                self.chat_info.config(text=f"Chat grupal: {self.current_chat}")
            else:
                self.chat_info.config(text=f"Chat con: {self.current_chat}")
        else:
            self.current_chat = None
            self.chat_info.config(text="Ningún chat seleccionado")

    def add_group(self, group_name, members):
        self.groups[group_name] = members
        self.users_tree.insert('', 'end', text=group_name, tags=('group',))
        self.display_message("ChatApp", f"Has sido añadido al grupo '{group_name}'.")

    def create_group(self):
        group_name = simpledialog.askstring("Crear Grupo", "Nombre del grupo:", parent=self.root)
        if group_name:
            user_selection_window = tk.Toplevel(self.root)
            user_selection_window.title("Seleccionar usuarios para el grupo")

            user_listbox = tk.Listbox(user_selection_window, selectmode=tk.MULTIPLE)
            user_listbox.pack(padx=10, pady=10, expand=True, fill=tk.BOTH)

            for user in self.users:
                if user['username'] != self.username:
                    user_listbox.insert(tk.END, user['username'])

            def confirm_selection():
                selected_indices = user_listbox.curselection()
                members = [user_listbox.get(i) for i in selected_indices]
                members.append(self.username)
                if members:
                    data = {
                        'type': 'create_group',
                        'group_name': group_name,
                        'members': members
                    }
                    self.socket.sendall(json.dumps(data).encode('utf-8') + b'\n')
                    user_selection_window.destroy()
                    self.display_message("ChatApp", f"Grupo '{group_name}' creado con éxito.")
                else:
                    messagebox.showwarning("Advertencia", "Selecciona al menos un usuario para el grupo.")

            confirm_button = ttk.Button(user_selection_window, text="Confirmar", command=confirm_selection)
            confirm_button.pack(pady=10)

    def send_message(self):
        message = self.message_input.get()
        if message and self.current_chat:
            data = {
                'type': 'message',
                'recipient': self.current_chat,
                'content': message
            }
            try:
                self.socket.sendall(json.dumps(data).encode('utf-8') + b'\n')
                if self.current_chat in self.groups:
                    self.display_message(f"Tú (en {self.current_chat})", message)
                else:
                    self.display_message("Tú", message)
                self.message_input.delete(0, tk.END)
            except Exception as e:
                logging.error(f"Error al enviar el mensaje: {e}")
        elif not self.current_chat:
            self.display_message("ChatApp", "Por favor, selecciona un destinatario o grupo antes de enviar un mensaje.")

            confirm_button = ttk.Button(user_selection_window, text="Confirmar", command=confirm_selection)
            confirm_button.pack(pady=10)


if __name__ == "__main__":
    client = ChatClient()
    client.connect()