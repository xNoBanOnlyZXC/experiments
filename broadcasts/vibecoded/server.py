import socket
import threading
import time
import json
import logging
import uuid
import os
import subprocess
import base64

import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template_string, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit
import cryptocode as cc

BROADCAST_IP = '255.255.255.255'
BROADCAST_PORT = 12345
TCP_SERVER_PORT = 12346
FLASK_PORT = 5000
ENCRYPTION_KEY = "YourSuperSecretKey123" # !!! ОБЯЗАТЕЛЬНО ИЗМЕНИТЕ ЭТОТ КЛЮЧ !!!

LOG_FILE = "server.log"
DOWNLOAD_FOLDER = "downloads" # Папка для сохранения скачанных с клиентов файлов

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler(LOG_FILE, encoding='utf-8'),
                        logging.StreamHandler()
                    ])
logger = logging.getLogger('AdminServer')

connected_clients = {}
client_sockets_lock = threading.Lock()

# Буферы для входящих файлов от клиентов
# {client_id: {file_id: {"name": "file.txt", "size": 12345, "received_chunks": 0, "total_chunks": N, "data": []}}}
file_transfer_buffers = {}
file_transfer_lock = threading.Lock()

app = Flask(__name__)
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# Создаем папку для скачиваний, если ее нет
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

class SocketIOHandler(logging.Handler):
    def emit(self, record):
        try:
            log_entry = self.format(record)
            socketio.emit('new_log_entry', {'data': log_entry})
        except Exception:
            pass

logger.addHandler(SocketIOHandler())

# ИСПРАВЛЕННЫЙ HTML_TEMPLATE - Использование {{ client_id }} вместо ${clientId} для ID элементов
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Админ-панель управления компьютерами</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background-color: #f4f4f4; color: #333; }
        .container { max-width: 1200px; margin: auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }
        h1, h2 { color: #0056b3; }
        .client-list, .log-output { margin-top: 20px; }
        .client-item { background: #e9e9e9; padding: 10px; margin-bottom: 5px; border-radius: 5px; display: flex; flex-direction: column; }
        .client-item.online { border-left: 5px solid #28a745; }
        .client-item.offline { border-left: 5px solid #dc3545; }
        .client-info-actions { display: flex; justify-content: space-between; align-items: center; width: 100%; margin-bottom: 10px;}
        .client-info { flex-grow: 1; }
        .client-actions { margin-left: 10px; }
        .client-actions form { display: inline-block; margin-right: 5px; }
        .log-area { width: 100%; background: #333; color: #eee; padding: 10px; border-radius: 5px; height: 300px; overflow-y: scroll; font-family: monospace; white-space: pre-wrap; box-sizing: border-box; }
        button { background-color: #007bff; color: white; padding: 8px 12px; border: none; border-radius: 4px; cursor: pointer; }
        button:hover { background-color: #0056b3; }
        input[type="text"], input[type="file"] { padding: 8px; border-radius: 4px; border: 1px solid #ccc; width: 200px; }
        .command-form { margin-top: 20px; padding: 15px; border: 1px solid #ccc; border-radius: 8px; background: #fff; }
        .command-form label { display: block; margin-bottom: 5px; font-weight: bold; }
        .command-form select, .command-form input[type="text"], .command-form textarea { width: calc(100% - 16px); padding: 8px; margin-bottom: 10px; border: 1px solid #ccc; border-radius: 4px; }
        .command-response { margin-top: 10px; padding: 10px; border: 1px solid #ddd; background: #f9f9f9; border-radius: 5px; max-height: 200px; overflow-y: auto; white-space: pre-wrap; }
        .file-list { margin-top: 10px; padding: 10px; border: 1px solid #eee; background: #fdfdfd; max-height: 250px; overflow-y: auto; }
        .file-list div { display: flex; justify-content: space-between; padding: 5px 0; border-bottom: 1px dotted #ccc; }
        .file-list div:last-child { border-bottom: none; }
        .file-list .file-item-name { flex-grow: 1; }
        .file-list .file-item-actions button { margin-left: 5px; }
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.min.js"></script>
</head>
<body>
    <div class="container">
        <h1>Панель управления локальными компьютерами</h1>

        <h2>Подключенные клиенты</h2>
        <div class="client-list">
            {% if clients %}
                {% for client_id, client_info in clients.items() %}
                <div class="client-item {{ 'online' if client_info.status == 'online' else 'offline' }}" id="client-{{ client_id }}">
                    <div class="client-info-actions">
                        <div class="client-info">
                            <strong>{{ client_info.name }} (ID: {{ client_id[:8] }}...)</strong><br>
                            IP: {{ client_info.address[0] }}:{{ client_info.address[1] }}<br>
                            Статус: <span id="status-{{ client_id }}">{{ client_info.status }}</span>
                        </div>
                        <div class="client-actions">
                            <div class="command-form">
                                <label for="command_type_{{ client_id }}">Выберите команду:</label>
                                <select id="command_type_{{ client_id }}" onchange="updateCommandInput('{{ client_id }}', this.value)">
                                    <option value="get_sysinfo">Получить инфо о системе</option>
                                    <option value="ping">Проверить соединение (ping)</option>
                                    <option value="shutdown">Выключить ПК</option>
                                    <option value="restart">Перезагрузить ПК</option>
                                    <option value="exec_cmd">Выполнить команду (CMD)</option>
                                    <option value="show_message">Показать сообщение</option>
                                    <option value="get_processes">Получить список процессов</option>
                                    <option value="kill_process">Завершить процесс (по имени/ID)</option>
                                    <option value="list_dir">Просмотреть папку</option>
                                    <option value="download_file_client">Скачать файл (с клиента)</option>
                                    <option value="upload_file_client">Загрузить файл (на клиент)</option>
                                    <option value="delete_path">Удалить файл/папку</option>
                                    <option value="create_folder">Создать папку</option>
                                    <option value="rename_path">Переименовать файл/папку</option>
                                </select>
                                <div id="command_text_container_{{ client_id }}" style="display: none;">
                                    <label for="command_text_{{ client_id }}">Параметр/Путь/Имя:</label>
                                    <input type="text" id="command_text_{{ client_id }}" placeholder="">
                                </div>
                                <div id="new_name_container_{{ client_id }}" style="display: none;">
                                    <label for="new_name_{{ client_id }}">Новое имя/путь (для переименования):</label>
                                    <input type="text" id="new_name_{{ client_id }}" placeholder="Новое имя/путь">
                                </div>
                                <div id="upload_file_input_container_{{ client_id }}" style="display: none;">
                                    <label for="upload_file_input_{{ client_id }}">Выберите файл для загрузки:</label>
                                    <input type="file" id="upload_file_input_{{ client_id }}">
                                </div>
                                <button onclick="mainSendCommand('{{ client_id }}')">Отправить</button>
                            </div>
                        </div>
                    </div>
                    <div class="command-response" id="command_response_{{ client_id }}">
                        {% if client_info.last_response %}
                            <strong>Последний ответ:</strong><br><pre>{{ client_info.last_response }}</pre>
                        {% endif %}
                    </div>
                    <div class="file-list" id="file_list_{{ client_id }}"></div>
                </div>
                {% endfor %}
            {% else %}
                <p>Нет подключенных клиентов.</p>
            {% endif %}
        </div>

        <h2>Логи сервера</h2>
        <div class="log-output">
            <textarea class="log-area" readonly></textarea>
        </div>
    </div>

    <script>
        var socket = io.connect('http://' + document.domain + ':' + location.port);
        var logArea = document.querySelector('.log-area');
        var clientListDiv = document.querySelector('.client-list');

        window.onload = function() {
            fetch('/get_full_log')
                .then(response => response.text())
                .then(data => {
                    logArea.value = data;
                    logArea.scrollTop = logArea.scrollHeight;
                })
                .catch(error => console.error('Error fetching full log:', error));
        };

        socket.on('new_log_entry', function(msg) {
            logArea.value += msg.data + '\\n';
            logArea.scrollTop = logArea.scrollHeight;
        });

        socket.on('new_client_connected', function(clientData) {
            const clientId = clientData.client_id;
            if (document.getElementById('client-' + clientId)) {
                return;
            }

            const clientItem = document.createElement('div');
            clientItem.id = 'client-' + clientId;
            clientItem.className = 'client-item online';
            clientItem.innerHTML = `
                <div class="client-info-actions">
                    <div class="client-info">
                        <strong>${clientData.name} (ID: ${clientId.substring(0, 8)}...)</strong><br>
                        IP: ${clientData.address[0]}:${clientData.address[1]}<br>
                        Статус: <span id="status-${clientId}">online</span>
                    </div>
                    <div class="client-actions">
                        <div class="command-form">
                            <label for="command_type_${clientId}">Выберите команду:</label>
                            <select id="command_type_${clientId}" onchange="updateCommandInput('${clientId}', this.value)">
                                <option value="get_sysinfo">Получить инфо о системе</option>
                                <option value="ping">Проверить соединение (ping)</option>
                                <option value="shutdown">Выключить ПК</option>
                                <option value="restart">Перезагрузить ПК</option>
                                <option value="exec_cmd">Выполнить команду (CMD)</option>
                                <option value="show_message">Показать сообщение</option>
                                <option value="get_processes">Получить список процессов</option>
                                <option value="kill_process">Завершить процесс (по имени/ID)</option>
                                <option value="list_dir">Просмотреть папку</option>
                                <option value="download_file_client">Скачать файл (с клиента)</option>
                                <option value="upload_file_client">Загрузить файл (на клиент)</option>
                                <option value="delete_path">Удалить файл/папку</option>
                                <option value="create_folder">Создать папку</option>
                                <option value="rename_path">Переименовать файл/папку</option>
                            </select>
                            <div id="command_text_container_${clientId}" style="display: none;">
                                <label for="command_text_${clientId}">Параметр/Путь/Имя:</label>
                                <input type="text" id="command_text_${clientId}" placeholder="">
                            </div>
                            <div id="new_name_container_${clientId}" style="display: none;">
                                <label for="new_name_${clientId}">Новое имя/путь (для переименования):</label>
                                <input type="text" id="new_name_${clientId}" placeholder="Новое имя/путь">
                            </div>
                            <div id="upload_file_input_container_${clientId}" style="display: none;">
                                <label for="upload_file_input_${clientId}">Выберите файл для загрузки:</label>
                                <input type="file" id="upload_file_input_${clientId}">
                            </div>
                            <button onclick="mainSendCommand('${clientId}')">Отправить</button>
                        </div>
                    </div>
                </div>
                <div class="command-response" id="command_response_${clientId}">
                    ${clientData.last_response ? '<strong>Последний ответ:</strong><br><pre>' + clientData.last_response + '</pre>' : ''}
                </div>
                <div class="file-list" id="file_list_${clientId}"></div>
            `;
            clientListDiv.appendChild(clientItem);
            // При добавлении нового клиента, нужно также вызвать updateCommandInput
            // чтобы корректно инициализировать видимость полей для новой формы
            updateCommandInput(clientId, document.getElementById('command_type_' + clientId).value);
        });

        socket.on('client_data_update', function(updateData) {
            const clientId = updateData.client_id;
            const clientItem = document.getElementById('client-' + clientId);
            if (clientItem) {
                const statusSpan = document.getElementById('status-' + clientId);
                if (statusSpan && updateData.status) {
                    statusSpan.textContent = updateData.status;
                    if (updateData.status === 'online') {
                        clientItem.classList.remove('offline');
                        clientItem.classList.add('online');
                    } else {
                        clientItem.classList.remove('online');
                        clientItem.classList.add('offline');
                    }
                }
                const responseDiv = document.getElementById('command_response_' + clientId);
                if (responseDiv && updateData.last_response !== undefined) {
                    responseDiv.innerHTML = `<strong>Последний ответ:</strong><br><pre>${updateData.last_response}</pre>`;
                }
                if (updateData.file_list || updateData.current_path !== undefined) {
                    displayFileList(clientId, updateData.file_list, updateData.current_path);
                }
            }
        });
        
        socket.on('file_transfer_status', function(data) {
            const client_id = data.client_id;
            const file_name = data.file_name;
            const message = data.message;
            const responseDiv = document.getElementById('command_response_' + client_id);
            if (responseDiv) {
                responseDiv.innerHTML = `<strong>${message}</strong>`;
            }
            if (data.status === 'error') {
                alert(`Ошибка передачи файла: ${file_name}\\n${message}`);
            }
        });

        // ИСПРАВЛЕНИЕ: Добавление автоматического клика для скачивания файла
        socket.on('file_download_ready', function(data) {
            const client_id = data.client_id;
            const file_name = data.file_name;
            const download_url = `/download/${file_name}`; 
            
            const responseDiv = document.getElementById('command_response_' + client_id);
            responseDiv.innerHTML = `<strong>Файл '${file_name}' готов к скачиванию!</strong><br><a href="${download_url}" target="_blank">Нажмите для скачивания</a>`;
            // alert(`Файл '${file_name}' успешно скачан с клиента и загрузка на ваш ПК началась.`);

            // Автоматический клик для инициирования загрузки в браузере
            const link = document.createElement('a');
            link.href = download_url;
            link.download = file_name; // Этот атрибут заставляет браузер скачать файл с указанным именем
            document.body.appendChild(link);
            link.click(); // Программно кликаем по ссылке
            document.body.removeChild(link); // Удаляем ссылку после использования
        });

        function updateCommandInput(clientId, commandType) {
            const commandInputContainer = document.getElementById('command_text_container_' + clientId);
            const commandInput = document.getElementById('command_text_' + clientId);
            const newNameContainer = document.getElementById('new_name_container_' + clientId);
            const newNameInput = document.getElementById('new_name_' + clientId);
            const uploadFileInputContainer = document.getElementById('upload_file_input_container_' + clientId);
            const uploadFileInput = document.getElementById('upload_file_input_' + clientId);
            
            // Проверка на null перед доступом к style
            if (commandInputContainer) commandInputContainer.style.display = 'none';
            if (newNameContainer) newNameContainer.style.display = 'none';
            if (uploadFileInputContainer) uploadFileInputContainer.style.display = 'none';
            
            if (commandInput) commandInput.value = '';
            if (newNameInput) newNameInput.value = '';
            if (uploadFileInput) uploadFileInput.value = '';

            let placeholder = '';
            let displayCommandInput = 'none';

            switch(commandType) {
                case 'exec_cmd':
                    placeholder = 'Введите команду CMD/Shell...';
                    displayCommandInput = 'block';
                    break;
                case 'show_message':
                    placeholder = 'Введите сообщение для показа...';
                    displayCommandInput = 'block';
                    break;
                case 'kill_process':
                    placeholder = 'Имя процесса или PID (например, "notepad.exe" или "1234")...';
                    displayCommandInput = 'block';
                    break;
                case 'delete_path':
                    placeholder = 'Путь к файлу/папке для удаления...';
                    displayCommandInput = 'block';
                    break;
                case 'create_folder':
                    placeholder = 'Путь для новой папки (например, "C:\\\\НоваяПапка")...';
                    displayCommandInput = 'block';
                    break;
                case 'list_dir':
                    placeholder = 'Путь к папке (например, "C:\\\\" или "/")...';
                    displayCommandInput = 'block';
                    // Если поле пустое и это list_dir, автоматически запросить список дисков
                    if (commandInput && !commandInput.value) { 
                        mainSendCommand(clientId, '', 'get_drives_list');
                    }
                    break;
                case 'download_file_client':
                    placeholder = 'Полный путь к файлу на клиенте для скачивания...';
                    displayCommandInput = 'block';
                    break;
                case 'upload_file_client':
                    placeholder = 'Полный путь на клиенте для сохранения файла (например, "C:\\\\new_file.txt")...';
                    displayCommandInput = 'block';
                    if (uploadFileInputContainer) uploadFileInputContainer.style.display = 'block';
                    break;
                case 'rename_path':
                    placeholder = 'Старый путь к файлу/папке...';
                    displayCommandInput = 'block';
                    if (newNameContainer) newNameContainer.style.display = 'block';
                    break;
                default:
                    placeholder = '';
                    displayCommandInput = 'none';
                    break;
            }
            if (commandInput) commandInput.placeholder = placeholder;
            if (commandInputContainer) commandInputContainer.style.display = displayCommandInput;
        }

        async function mainSendCommand(clientId, pathOverride = null, commandTypeOverride = null, newNameOverride = null) {
            const commandTypeSelect = document.getElementById('command_type_' + clientId);
            const commandInput = document.getElementById('command_text_' + clientId);
            const newNameInput = document.getElementById('new_name_' + clientId);
            const uploadFileInput = document.getElementById('upload_file_input_' + clientId);
            const responseDiv = document.getElementById('command_response_' + clientId);
            
            const commandType = commandTypeOverride || (commandTypeSelect ? commandTypeSelect.value : '');
            const commandText = pathOverride !== null ? pathOverride : (commandInput ? commandInput.value : '');
            const newName = newNameOverride !== null ? newNameOverride : (newNameInput ? newNameInput.value : '');
            const fileToUpload = uploadFileInput ? uploadFileInput.files[0] : null;

            if (responseDiv) responseDiv.textContent = 'Отправка команды...';

            let body = {
                client_id: clientId,
                command_type: commandType,
                command_text: commandText,
                new_name: newName
            };

            if (commandType === 'upload_file_client' && fileToUpload) {
                const reader = new FileReader();
                reader.onload = async function(e) {
                    const fileContent = e.target.result; // Base64 encoded string
                    body.file_content = fileContent;

                    try {
                        const response = await fetch('/send_command', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(body)
                        });
                        const data = await response.json();
                        if (responseDiv) {
                            if (data.status === 'success') {
                                responseDiv.textContent = 'Команда отправлена. Ожидание ответа...';
                            } else {
                                responseDiv.textContent = 'Ошибка: ' + data.message;
                            }
                        }
                    } catch (error) {
                        console.error('Error sending upload command:', error);
                        if (responseDiv) responseDiv.textContent = 'Ошибка отправки: ' + error.message;
                    }
                };
                reader.onerror = function() {
                    if (responseDiv) responseDiv.textContent = 'Ошибка чтения файла.';
                };
                reader.readAsDataURL(fileToUpload); // Reads as Data URL (Base64)
            } else {
                try {
                    const response = await fetch('/send_command', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(body)
                    });
                    const data = await response.json();
                    if (responseDiv) {
                        if (data.status === 'success') {
                            responseDiv.textContent = 'Команда отправлена. Ожидание ответа...';
                        } else {
                            responseDiv.textContent = 'Ошибка: ' + data.message;
                        }
                    }
                } catch (error) {
                    console.error('Error sending command:', error);
                    if (responseDiv) responseDiv.textContent = 'Ошибка отправки: ' + error.message;
                }
            }
        }

        function displayFileList(clientId, fileList, currentPath) {
            const fileListDiv = document.getElementById('file_list_' + clientId);
            if (!fileListDiv) return; // Проверка на существование элемента

            fileListDiv.innerHTML = '';

            if (currentPath !== null && currentPath !== undefined) {
                fileListDiv.innerHTML += `<h4>Содержимое папки: ${currentPath}</h4>`;
            } else {
                fileListDiv.innerHTML += `<h4>Содержимое: (Загрузка или выбор диска)</h4>`;
            }

            if (!fileList || fileList.length === 0) {
                fileListDiv.innerHTML += '<p>Папка пуста или не существует. <br>Попробуйте "C:\\\\" или "/" или получите список дисков.</p>';
                if ((currentPath && fileList && fileList.length === 0) || !currentPath) {
                     fileListDiv.innerHTML += `<button onclick="mainSendCommand('${clientId}', '', 'get_drives_list')">Показать диски</button>`;
                }
                return;
            }

            if (currentPath) {
                const normalizedPath = currentPath.replace(/\\\\/g, '/');
                const isWindowsRoot = /^[A-Za-z]:\/?$/.test(currentPath);
                const isUnixRoot = normalizedPath === '/';

                if (!isWindowsRoot && !isUnixRoot) {
                    let parentPath;
                    if (currentPath.includes('/') && currentPath.lastIndexOf('/') > 0) {
                        parentPath = currentPath.substring(0, currentPath.lastIndexOf('/'));
                        if (parentPath === '') parentPath = '/';
                    } else if (currentPath.includes('\\\\') && currentPath.lastIndexOf('\\\\') > 2) {
                        parentPath = currentPath.substring(0, currentPath.lastIndexOf('\\\\'));
                        if (parentPath.length === 2 && parentPath.endsWith(':')) parentPath += '\\\\';
                    } else {
                        parentPath = null;
                    }
                    
                    if (parentPath !== null) {
                        const encodedParentPath = encodeURIComponent(parentPath);
                        const parentItem = document.createElement('div');
                        parentItem.innerHTML = `<span class="file-item-name">.. (На уровень выше)</span>
                            <div class="file-item-actions">
                                <button onclick="mainSendCommand('${clientId}', decodeURIComponent('${encodedParentPath}'), 'list_dir')">Перейти</button>
                            </div>`;
                        fileListDiv.appendChild(parentItem);
                    }
                }
            }

            fileList.forEach(item => {
                const itemDiv = document.createElement('div');
                const isDir = item.type === 'directory';
                const icon = isDir ? '📁' : '📄';
                const size = item.size !== undefined && !isDir ? ` (${(item.size / 1024).toFixed(2)} KB)` : '';

                const encodedFullPath = encodeURIComponent(item.full_path);
                const encodedItemName = encodeURIComponent(item.name);

                itemDiv.innerHTML = `
                    <span class="file-item-name">${icon} ${item.name}${size}</span>
                    <div class="file-item-actions">
                        ${isDir ? `<button onclick="mainSendCommand('${clientId}', decodeURIComponent('${encodedFullPath}'), 'list_dir')">Открыть</button>` : ''}
                        ${!isDir ? `<button onclick="mainSendCommand('${clientId}', decodeURIComponent('${encodedFullPath}'), 'download_file_client')">Скачать</button>` : ''}
                        <button onclick="if(confirm('Вы уверены, что хотите удалить ${item.name}?')) mainSendCommand('${clientId}', decodeURIComponent('${encodedFullPath}'), 'delete_path')">Удалить</button>
                        <button onclick="promptRename('${clientId}', decodeURIComponent('${encodedFullPath}'), decodeURIComponent('${encodedItemName}'))">Переим.</button>
                    </div>
                `;
                fileListDiv.appendChild(itemDiv);
            });
        }

        function promptRename(clientId, oldPath, oldName) {
            const newName = prompt(`Переименовать '${oldName}' в:`, oldName);
            if (newName) {
                mainSendCommand(clientId, oldPath, 'rename_path', newName);
            }
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    with client_sockets_lock:
        current_clients = connected_clients.copy()
    return render_template_string(HTML_TEMPLATE, clients=current_clients)

@app.route('/get_full_log')
def get_full_log():
    log_content = "Лог файл пока пуст или не найден."
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                log_content = f.read()
        except Exception as e:
            log_content = f"Ошибка чтения лог-файла: {e}"
    return log_content

@app.route('/send_command', methods=['POST'])
def send_command():
    data = request.json
    client_id = data.get('client_id')
    command_type = data.get('command_type')
    command_text = data.get('command_text', '')
    new_name = data.get('new_name', '')
    file_content_base64 = data.get('file_content')

    with client_sockets_lock:
        client_info = connected_clients.get(client_id)

    if not client_info or client_info.get("status") != "online":
        return jsonify({"status": "error", "message": "Клиент не найден или не в сети."})

    client_socket = client_info["socket"]
    
    command_payload = {
        "text": command_text,
        "new_name": new_name
    }
    
    if command_type == "upload_file_client" and file_content_base64:
        if "," in file_content_base64:
            file_content_base64 = file_content_base64.split(",", 1)[1]
        command_payload["file_content"] = file_content_base64

    command_packet = {
        "type": command_type,
        "payload": command_payload
    }

    try:
        encrypted_command = cc.encrypt(json.dumps(command_packet), ENCRYPTION_KEY)
        client_socket.sendall((encrypted_command + "\n").encode('utf-8'))
        logger.info(f"Команда '{command_type}' отправлена клиенту {client_id[:8]}...")
        return jsonify({"status": "success", "message": "Команда отправлена."})
    except Exception as e:
        logger.error(f"Ошибка при отправке команды клиенту {client_id}: {e}")
        with client_sockets_lock:
            if client_id in connected_clients:
                # Отмечаем клиента как оффлайн только если это тот же сокет
                if connected_clients[client_id]["socket"] == client_socket:
                    connected_clients[client_id]["status"] = "offline"
                    try:
                        connected_clients[client_id]["socket"].shutdown(socket.SHUT_RDWR)
                        connected_clients[client_id]["socket"].close()
                    except Exception as close_e:
                        logger.error(f"Ошибка при закрытии сокета для {client_id[:8]}... после ошибки отправки: {close_e}")
                    socketio.emit('client_data_update', {'client_id': client_id, 'status': 'offline'})
        return jsonify({"status": "error", "message": f"Ошибка отправки команды: {e}"})

@app.route('/download/<filename>')
def download_file_from_server(filename):
    try:
        return send_from_directory(DOWNLOAD_FOLDER, filename, as_attachment=True)
    except FileNotFoundError:
        return "Файл не найден.", 404
    except Exception as e:
        logger.error(f"Ошибка при попытке скачать файл '{filename}': {e}")
        return f"Ошибка при скачивании файла: {e}", 500

def broadcast_announcer():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        sock.bind(('0.0.0.0', BROADCAST_PORT))
        logger.info(f"Широковещательный сокет привязан к 0.0.0.0:{BROADCAST_PORT}")
    except Exception as e:
        logger.error(f"Не удалось привязать широковещательный сокет к 0.0.0.0:{BROADCAST_PORT}: {e}")

    local_ip = '127.0.0.1'
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception as e:
        logger.warning(f"Не удалось определить локальный IP-адрес автоматически: {e}. Используем {local_ip}. Убедитесь, что клиенты смогут подключиться.")

    connection_info = {
        "ip": local_ip,
        "port": TCP_SERVER_PORT
    }
    encrypted_info = cc.encrypt(json.dumps(connection_info), ENCRYPTION_KEY)
    logger.info(f"Шифрованные данные подключения: {encrypted_info}")

    while True:
        try:
            sock.sendto(encrypted_info.encode('utf-8'), (BROADCAST_IP, BROADCAST_PORT))
        except Exception as e:
            logger.error(f"Ошибка при широковещательной рассылке: {e}")
        time.sleep(5)

def handle_client(conn, addr, client_id):
    logger.info(f"Установлено новое TCP-соединение от {addr} с ID клиента: {client_id[:8]}...")
    with client_sockets_lock:
        client_info = {"address": addr, "socket": conn, "name": f"Client-{addr[0]}", "status": "online", "last_response": "", "current_path": [], "file_list": []}
        # Обновляем client_info, если он уже есть, или добавляем новый
        connected_clients[client_id] = client_info
        socketio.emit('new_client_connected', {
            'client_id': client_id,
            'name': client_info['name'],
            'address': client_info['address'],
            'status': client_info['status'],
            'last_response': client_info['last_response']
        })

    buffer = ""
    conn.settimeout(30)

    try:
        while True:
            try:
                data = conn.recv(4096 * 4)
                if not data:
                    logger.warning(f"Клиент {addr} (ID: {client_id[:8]}...) отключился (получены пустые данные).")
                    break
            except socket.timeout:
                continue
            except Exception as e:
                logger.error(f"Ошибка при получении данных от {addr} (ID: {client_id[:8]}...): {e}")
                break

            buffer += data.decode('utf-8')

            while "\n" in buffer:
                message, buffer = buffer.split("\n", 1)
                if not message.strip():
                    continue

                try:
                    decrypted_message = cc.decrypt(message.strip(), ENCRYPTION_KEY)
                    if decrypted_message is None:
                        logger.warning(f"Не удалось расшифровать сообщение от {addr}. Возможно, неверный ключ или поврежденные данные. Сообщение (часть): {message.strip()[:100]}...")
                        continue

                    response_data = json.loads(decrypted_message)
                    response_type = response_data.get("type", "unknown")
                    response_payload = response_data.get("payload", "")
                    
                    if response_type == "keep_alive":
                        continue

                    if response_type == "file_transfer_start":
                        with file_transfer_lock:
                            file_id = response_payload.get("file_id")
                            file_name = response_payload.get("file_name", "unknown_file")
                            total_size = response_payload.get("total_size", 0)

                            if client_id not in file_transfer_buffers:
                                file_transfer_buffers[client_id] = {}
                            
                            file_transfer_buffers[client_id][file_id] = {
                                "name": file_name,
                                "total_size": total_size,
                                "received_data": [],
                                "received_size": 0
                            }
                            logger.info(f"Начата передача файла '{file_name}' (ID: {file_id[:8]}...) от {client_id[:8]}... Размер: {total_size} байт.")
                            socketio.emit('file_transfer_status', {
                                'client_id': client_id,
                                'file_name': file_name,
                                'status': 'in_progress',
                                'message': f"Начато получение файла: '{file_name}' ({total_size} байт)..."
                            })
                        continue
                    
                    elif response_type == "file_chunk":
                        with file_transfer_lock:
                            file_id = response_payload.get("file_id")
                            if client_id not in file_transfer_buffers or file_id not in file_transfer_buffers[client_id]:
                                logger.error(f"Получен чанк для неизвестной или несвязанной передачи файла. File ID: {file_id}, Client ID: {client_id}")
                                socketio.emit('file_transfer_status', {
                                    'client_id': client_id,
                                    'file_name': "unknown_file",
                                    'status': 'error',
                                    'message': "Получен чанк для неизвестной передачи файла."
                                })
                                continue

                            current_buffer = file_transfer_buffers[client_id][file_id]
                            chunk_data = base64.b64decode(response_payload["chunk"])
                            current_buffer["received_data"].append(chunk_data)
                            current_buffer["received_size"] += len(chunk_data)

                            if current_buffer["received_size"] >= current_buffer["total_size"]:
                                file_name_safe = os.path.basename(current_buffer["name"])
                                target_path = os.path.join(DOWNLOAD_FOLDER, file_name_safe)
                                
                                counter = 1
                                original_target_name, original_ext = os.path.splitext(file_name_safe)
                                while os.path.exists(target_path):
                                    target_path = os.path.join(DOWNLOAD_FOLDER, f"{original_target_name}_{counter}{original_ext}")
                                    file_name_safe = os.path.basename(target_path)
                                    counter += 1

                                full_file_data = b"".join(current_buffer["received_data"])

                                try:
                                    with open(target_path, "wb") as f:
                                        f.write(full_file_data)
                                    logger.info(f"Файл '{file_name_safe}' успешно сохранен в '{DOWNLOAD_FOLDER}'.")
                                    socketio.emit('file_download_ready', {
                                        'client_id': client_id, 
                                        'file_name': file_name_safe
                                    })
                                except Exception as e:
                                    logger.error(f"Ошибка сохранения файла '{file_name_safe}': {e}")
                                    socketio.emit('file_transfer_status', {
                                        'client_id': client_id, 
                                        'file_name': file_name_safe,
                                        'status': 'error',
                                        'message': f"Ошибка сохранения файла на сервере: {e}"
                                    })
                                del file_transfer_buffers[client_id][file_id]
                            else:
                                pass
                        continue
                    
                    if response_type == "drives_list":
                        logger.info(f"Получен список дисков от {client_id[:8]}...: {response_payload}")
                        with client_sockets_lock:
                            if client_id in connected_clients:
                                connected_clients[client_id]["last_response"] = "Список дисков получен."
                                connected_clients[client_id]["file_list"] = [{"name": d, "full_path": d, "type": "directory"} for d in response_payload]
                                connected_clients[client_id]["current_path"] = None
                                socketio.emit('client_data_update', {
                                    'client_id': client_id,
                                    'last_response': connected_clients[client_id]["last_response"],
                                    'status': connected_clients[client_id]["status"],
                                    'file_list': connected_clients[client_id]["file_list"],
                                    'current_path': connected_clients[client_id]["current_path"]
                                })
                        continue
                    
                    logger.info(f"Получен ответ от {client_id[:8]}... ({response_type}): {response_payload}")

                    with client_sockets_lock:
                        if client_id in connected_clients:
                            if isinstance(response_payload, dict) or isinstance(response_payload, list):
                                connected_clients[client_id]["last_response"] = json.dumps(response_payload, indent=2, ensure_ascii=False)
                            else:
                                connected_clients[client_id]["last_response"] = str(response_payload)
                            
                            if response_type == "dir_list":
                                connected_clients[client_id]["file_list"] = response_payload.get("items", [])
                                connected_clients[client_id]["current_path"] = response_payload.get("current_path")
                                socketio.emit('client_data_update', {
                                    'client_id': client_id,
                                    'last_response': connected_clients[client_id]["last_response"],
                                    'status': connected_clients[client_id]["status"],
                                    'file_list': connected_clients[client_id]["file_list"],
                                    'current_path': connected_clients[client_id]["current_path"]
                                })
                            else:
                                socketio.emit('client_data_update', {
                                    'client_id': client_id,
                                    'last_response': connected_clients[client_id]["last_response"],
                                    'status': connected_clients[client_id]["status"]
                                })
                            logger.info(f"Обновлен last_response для клиента {client_id[:8]}...")

                except json.JSONDecodeError:
                    logger.warning(f"Некорректный JSON от {addr}: {decrypted_message}")
                except Exception as e:
                    logger.error(f"Ошибка при обработке сообщения от {addr}: {e} (Сообщение: {message})")

    except ConnectionResetError:
        logger.warning(f"Соединение с клиентом {addr} (ID: {client_id[:8]}...) было сброшено.")
    except Exception as e:
        logger.error(f"Ошибка в потоке клиента {addr} (ID: {client_id[:8]}...): {e}")
    finally:
        with client_sockets_lock:
            if client_id in connected_clients:
                if connected_clients[client_id]["socket"] == conn:
                    try:
                        connected_clients[client_id]["socket"].shutdown(socket.SHUT_RDWR)
                        connected_clients[client_id]["socket"].close()
                    except Exception as e:
                        logger.error(f"Ошибка при закрытии сокета для {client_id[:8]}... в finally: {e}")
                
                connected_clients[client_id]["status"] = "offline"
                logger.info(f"Клиент {addr} (ID: {client_id[:8]}...) отключился. Отмечен как оффлайн.")
                socketio.emit('client_data_update', {'client_id': client_id, 'status': 'offline'})

def tcp_server():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    server_socket.bind(('0.0.0.0', TCP_SERVER_PORT))
    server_socket.listen(5)
    logger.info(f"TCP-сервер запущен и слушает на порту {TCP_SERVER_PORT}")

    while True:
        try:
            conn, addr = server_socket.accept()
            
            client_id_from_client = None
            try:
                conn.settimeout(5) 
                first_data = conn.recv(4096).decode('utf-8')
                conn.settimeout(None)
                
                if "\n" in first_data:
                    first_message, _ = first_data.split("\n", 1)
                    decrypted_first_message = cc.decrypt(first_message.strip(), ENCRYPTION_KEY)
                    if decrypted_first_message:
                        parsed_first_message = json.loads(decrypted_first_message)
                        if parsed_first_message.get("type") == "client_connect":
                            client_id_from_client = parsed_first_message["payload"]["client_id"]
                            client_name = parsed_first_message["payload"].get("name", f"Client-{addr[0]}")
                            logger.info(f"Получен ID клиента '{client_id_from_client[:8]}...' и имя '{client_name}' при первом подключении от {addr}.")
                            
                            with client_sockets_lock:
                                if client_id_from_client in connected_clients:
                                    logger.warning(f"Клиент ID {client_id_from_client[:8]}... уже существует в connected_clients. Закрываю старый сокет и обновляю данные.")
                                    try:
                                        connected_clients[client_id_from_client]["socket"].shutdown(socket.SHUT_RDWR)
                                        connected_clients[client_id_from_client]["socket"].close()
                                    except Exception as e:
                                        logger.error(f"Ошибка при закрытии старого сокета для {client_id_from_client[:8]}...: {e}")
                                    
                                    connected_clients[client_id_from_client]["socket"] = conn
                                    connected_clients[client_id_from_client]["address"] = addr
                                    connected_clients[client_id_from_client]["name"] = client_name
                                    connected_clients[client_id_from_client]["status"] = "online"
                                    # Также обновляем last_response, если оно есть, чтобы оно не пропадало при переподключении
                                    if "last_response" not in connected_clients[client_id_from_client]:
                                        connected_clients[client_id_from_client]["last_response"] = ""
                                    if "current_path" not in connected_clients[client_id_from_client]:
                                        connected_clients[client_id_from_client]["current_path"] = []
                                    if "file_list" not in connected_clients[client_id_from_client]:
                                        connected_clients[client_id_from_client]["file_list"] = []

                                    socketio.emit('client_data_update', {
                                        'client_id': client_id_from_client, 
                                        'status': 'online', 
                                        'name': client_name,
                                        'address': addr,
                                        'last_response': connected_clients[client_id_from_client]["last_response"]
                                    })
                                    eventlet.spawn(handle_client, conn, addr, client_id_from_client)
                                    continue # Продолжаем цикл accept, чтобы принять следующее соединение
                                else:
                                    client_id = client_id_from_client
                                    eventlet.spawn(handle_client, conn, addr, client_id)
                                    logger.info(f"Принято новое соединение от {addr}. Запущен поток обработки клиента ID: {client_id[:8]}...")
                        else:
                            logger.warning(f"Первое сообщение от {addr} не является 'client_connect'. Отбрасываю соединение.")
                            conn.close()
                            continue
                    else:
                        logger.warning(f"Не удалось расшифровать первое сообщение от {addr}. Отбрасываю соединение.")
                        conn.close()
                        continue
                else:
                    logger.warning(f"Неполное первое сообщение от {addr}. Отбрасываю соединение.")
                    conn.close()
                    continue
            except socket.timeout:
                logger.warning(f"Таймаут получения первого сообщения от {addr}. Закрываю соединение.")
                conn.close()
                continue
            except Exception as e:
                logger.error(f"Ошибка при обработке первого сообщения от {addr}: {e}. Закрываю соединение.")
                conn.close()
                continue

        except KeyboardInterrupt:
            logger.info("TCP-сервер остановлен.")
            break
        except Exception as e:
            logger.error(f"Ошибка при приеме нового соединения: {e}")
    server_socket.close()

if __name__ == "__main__":
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            f.write("Начало лога сервера...\n")

    eventlet.spawn(broadcast_announcer)
    logger.info("Поток широковещания запущен.")

    eventlet.spawn(tcp_server)
    logger.info("Поток TCP-сервера запущен.")

    logger.info(f"Запуск Flask-сервера с SocketIO на http://127.0.0.1:{FLASK_PORT}")
    socketio.run(app, host='0.0.0.0', port=FLASK_PORT, debug=False)