import subprocess
import time
import datetime
import re

# ---- НАСТРОЙКИ ----
PHONE_MACS = {
    "2E:7C:02:59:7B:E2",
    "2E:8C:C5:DA:35:EE",
    "BC:A5:A9:B2:F9:AA",
    "04:72:95:1A:1C:76",
    # при необходимости добавь сюда MAC телефона на 2.4 ГГц (если включён приватный MAC)
}

# Интерфейсы точек доступа (5 ГГц и 2.4 ГГц):
AP_INTERFACES = ["phy0-ap0", "phy1-ap0"]

CHECK_INTERVAL = 600                 # секунд между проверками, когда телефон дома
CLEANING_CHECK_INTERVAL = 60         # проверка во время уборки
STOP_CLEANING_THRESHOLD = 25 * 60    # когда прерывать уборку, если хозяин вернулся (сек)
MIN_CLEAN_INTERVAL = 8 * 3600        # «не чаще чем раз в N часов»

ROUTER_IP = "192.168.1.1"
VACUUM_IP = "192.168.1.193"
VACUUM_TOKEN = "534445364a756f6930657a74666c646f"

last_run_time = 0

def get_current_time():
    return datetime.datetime.now().strftime("%d-%m %H:%M:%S")

def get_connected_devices():
    """
    Собирает assoclist со всех заданных AP-интерфейсов и возвращает агрегированный текст.
    Только iwinfo, без лишней «магии». Ошибки не сыплем в лог.
    """
    outputs = []
    for iface in AP_INTERFACES:
        try:
            result = subprocess.run(
                ['ssh', f'root@{ROUTER_IP}', 'iwinfo', iface, 'assoclist'],
                capture_output=True, text=True, check=True, timeout=8
            )
            if result.stdout:
                outputs.append(f"[{iface}]\n{result.stdout}")
        except Exception:
            # Тихо игнорируем, чтобы лог не зарастал шумом при временных сбоях
            pass
    return "\n".join(outputs)

def is_phone_connected():
    assoc_text = get_connected_devices().upper()
    found = any(mac.upper() in assoc_text for mac in PHONE_MACS)
    src_info = ", ".join(AP_INTERFACES)
    print(f"{get_current_time()} - Проверка ассоциаций на интерфейсах: {src_info}")
    print(f"{get_current_time()} - Телефон: {'в сети' if found else 'отсутствует'}")
    return found

def get_vacuum_status():
    try:
        result = subprocess.run(
            ["mirobo", "--ip", VACUUM_IP, "--token", VACUUM_TOKEN, "status"],
            capture_output=True, text=True, check=True, timeout=15
        )
        output = result.stdout
        state_match = re.search(r"State:\s+(.+)", output)
        error_match = re.search(r"Error:\s+(.+)", output)

        state = state_match.group(1).strip() if state_match else "Unknown"
        error = error_match.group(1).strip() if error_match else ""

        return state, error
    except subprocess.CalledProcessError as e:
        print(f"{get_current_time()} - Ошибка при получении статуса пылесоса: {e}")
        return "Unknown", "Command error"
    except subprocess.TimeoutExpired:
        print(f"{get_current_time()} - Таймаут команды статуса пылесоса")
        return "Unknown", "Timeout"

def start_cleaning():
    print(f"{get_current_time()} - Запуск пылесоса...")
    try:
        subprocess.run(
            ["mirobo", "--ip", VACUUM_IP, "--token", VACUUM_TOKEN, "start"],
            check=True, timeout=15
        )
        print(f"{get_current_time()} - Пылесос запущен.")
        return True
    except Exception as e:
        print(f"{get_current_time()} - Ошибка запуска пылесоса: {e}")
        return False

def stop_cleaning():
    print(f"{get_current_time()} - Остановка уборки и возвращение на базу...")
    try:
        subprocess.run(
            ["mirobo", "--ip", VACUUM_IP, "--token", VACUUM_TOKEN, "home"],
            check=True, timeout=15
        )
        print(f"{get_current_time()} - Пылесос возвращён на базу.")
    except Exception as e:
        print(f"{get_current_time()} - Ошибка при остановке пылесоса: {e}")

def main():
    global last_run_time
    
    print(f"{get_current_time()} - Стартовая отсрочка 2 ч. (ожидание 120 мин)...")
    time.sleep(2 * 3600)

    while True:
        print(f"{get_current_time()} - Проверка наличия телефона...")

        if is_phone_connected():
            print(f"{get_current_time()} - Телефон дома. Повтор через {CHECK_INTERVAL // 60} мин.")
            time.sleep(CHECK_INTERVAL)
            continue

        state, error = get_vacuum_status()
        if state != "Charging" or error:
            print(f"{get_current_time()} - Пылесос не готов: {state}{' / ' + error if error else ''}. Повтор через {CHECK_INTERVAL // 60} мин.")
            time.sleep(CHECK_INTERVAL)
            continue

        print(f"{get_current_time()} - Телефона нет. Пытаемся запустить уборку.")
        if not start_cleaning():
            time.sleep(CHECK_INTERVAL)
            continue

        cleaning_completed = True
        for _ in range(STOP_CLEANING_THRESHOLD // CLEANING_CHECK_INTERVAL):
            time.sleep(CLEANING_CHECK_INTERVAL)

            if is_phone_connected():
                print(f"{get_current_time()} - Телефон появился. Прерываем уборку.")
                stop_cleaning()
                cleaning_completed = False
                break

            state, error = get_vacuum_status()
            if state == "Error" or error:
                print(f"{get_current_time()} - Обнаружена ошибка пылесоса: {error}. Прерываем уборку.")
                stop_cleaning()
                cleaning_completed = False
                break

        if cleaning_completed:
            last_run_time = time.time()
            print(f"{get_current_time()} - Уборка завершена. Пауза {MIN_CLEAN_INTERVAL // 3600} ч.")
            time.sleep(MIN_CLEAN_INTERVAL)
        else:
            print(f"{get_current_time()} - Уборка прервана. Повтор через {CHECK_INTERVAL // 60} мин.")

if __name__ == "__main__":
    main()

