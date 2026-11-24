# 🎓 Personal Assistant — учебный проект для практики Docker

Простое FastAPI-приложение, которое используется как основа для лабораторной работы по Docker.

## 📁 Структура проекта

```
simple_example/
├── app/
│   └── main.py              # FastAPI-приложение
├── requirements.txt          # Python-зависимости
└── README.md
```

## 💻 Локальный запуск (без Docker)

### 1. Установить зависимости

```bash
cd simple_example
pip install -r requirements.txt
```

### 2. Задать переменные окружения

**macOS / Linux:**

```bash
export APP_OWNER=ВашеИмя
export APP_SECRET=ваш_секретный_ключ
```

**Windows (PowerShell):**

```powershell
$env:APP_OWNER="ВашеИмя"
$env:APP_SECRET="ваш_секретный_ключ"
```

**Windows (CMD):**

```cmd
set APP_OWNER=ВашеИмя
set APP_SECRET=ваш_секретный_ключ
```

> Если не задать переменные, приложение запустится со значениями по умолчанию: `anonymous` / `default_secret`.

### 3. Запустить сервер

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Флаг `--reload` автоматически перезапускает сервер при изменении кода.

### 4. Открыть в браузере

- Приложение: **http://localhost:8000**
- Swagger UI: **http://localhost:8000/docs**

## 📡 Эндпоинты

| Метод | URL | Описание |
|-------|-----|----------|
| GET | `/` | Главная страница — приветствие и список эндпоинтов |
| GET | `/health` | Healthcheck — статус приложения |
| GET | `/docs` | Swagger UI — интерактивная документация (встроена в FastAPI) |
| GET | `/me` | Информация о владельце (из переменных окружения) |
| GET | `/secret/{key}` | Проверка секретного ключа — убедитесь, что `APP_SECRET` пробрасывается |
| GET | `/weather/{city}` | Текущая погода в городе через Open-Meteo API |
| POST | `/notes` | Создать заметку (тело: `{"text": "..."}`) |
| GET | `/notes` | Получить все заметки |

### Примеры запросов

```bash
# Главная
curl http://localhost:8000/

# Погода в Москве
curl http://localhost:8000/weather/Moscow

# Проверка секретного ключа
curl http://localhost:8000/secret/ваш_секретный_ключ

# Создать заметку
curl -X POST http://localhost:8000/notes \
  -H "Content-Type: application/json" \
  -d '{"text": "Моя первая заметка"}'

# Получить заметки
curl http://localhost:8000/notes
```

## 🔑 Переменные окружения

| Переменная | Описание | Значение по умолчанию |
|------------|----------|-----------------------|
| `APP_OWNER` | Имя владельца приложения | `anonymous` |
| `APP_SECRET` | Секретный ключ для эндпоинта `/secret/{key}` | `default_secret` |


## 🌤 API погоды — важно для пользователей из РФ

Эндпоинт `/weather/{city}` обращается к открытому API **[Open-Meteo](https://open-meteo.com/)** (бесплатный, без ключа):

1. **Геокодинг** — `geocoding-api.open-meteo.com` — получает координаты города
2. **Прогноз** — `api.open-meteo.com` — получает текущую погоду по координатам

### ⚠️ Блокировки РКН

Домены `open-meteo.com` могут быть недоступны из российских сетей из-за блокировок РКН.

Если эндпоинт `/weather/{city}` возвращает ошибку таймаута — **необходимо использовать средства обхода блокировок:**

- **VPN** — включите VPN на машине, где запущен Docker

## ✅ Как проверить, что всё работает

1. `curl http://localhost:8000/` — должен вернуть приветствие с вашим именем
2. `curl http://localhost:8000/me` — должен показать `secret_prefix` (первые 6 символов вашего ключа)
3. `curl http://localhost:8000/secret/ваш_ключ` — должен вернуть `LAB2_SUCCESS_ВАШЕИМЯ`
4. `curl http://localhost:8000/weather/London` — должен вернуть температуру, влажность, ветер
5. `docker inspect --format='{{.State.Health.Status}}' personal-assistant` — должен вернуть `healthy`

## Хранение данных

В Docker Compose данные PostgreSQL хранятся в томе `yamaleeva-db-data`. Для запуска прежней версии используются `docker-compose.yml` и локальный файл `.env` по образцу `.env.example`.

## Kubernetes — ЛР5

Команды выполняются из `solutions/assist-py` в Ubuntu или WSL2. Для WSL2 включите интеграцию Ubuntu в Docker Desktop. Установите [Minikube](https://minikube.sigs.k8s.io/docs/start/) и откройте Docker Desktop.

```bash
docker version
minikube start -p lab5 --driver=docker --cpus=2 --memory=4096
# Дальше в этом терминале можно использовать встроенный kubectl.
kubectl() { minikube -p lab5 kubectl -- "$@"; }

docker build -t yamaleeva-assist-py:lab5 .
minikube -p lab5 image load --overwrite yamaleeva-assist-py:lab5
minikube -p lab5 image ls | grep yamaleeva
```

Создайте локальный Secret. Введите учебный ключ по формуле из задания и учебный пароль PostgreSQL. Не снимайте экран во время ввода. Существующий пароль БД при повторном запуске с тем же PVC сохраняйте.

```bash
read -rsp 'APP_SECRET: ' APP_SECRET; echo
read -rsp 'POSTGRES_PASSWORD: ' PG_PASSWORD; echo
(umask 077
 kubectl create secret generic yamaleeva-app-secret  \
   --from-literal=APP_SECRET="$APP_SECRET"  \
   --from-literal=POSTGRES_PASSWORD="$PG_PASSWORD"  \
   --dry-run=client -o yaml > k8s/app-secret.yaml)
unset APP_SECRET PG_PASSWORD
```

Примените рабочий Secret, конфигурацию и манифесты. Файл `app-secret.example.yaml` служит образцом.

```bash
kubectl apply -f k8s/app-secret.yaml -f k8s/app-configmap.yaml
kubectl apply -f k8s/postgres-pvc.yaml -f k8s/postgres-service.yaml -f k8s/postgres-deployment.yaml
kubectl apply -f k8s/redis-service.yaml -f k8s/redis-deployment.yaml
kubectl apply -f k8s/app-service.yaml -f k8s/app-deployment.yaml
kubectl rollout status deployment/yamaleeva-app --timeout=180s
kubectl get pods -o wide
kubectl get svc,pvc
kubectl describe pod -l app=yamaleeva-app
kubectl get cm yamaleeva-app-config -o jsonpath='{.data.APP_OWNER}{"\n"}'
```

Оставьте этот терминал открытым после запуска проброса порта.

```bash
kubectl port-forward svc/yamaleeva-app 8083:8083
```

Во втором терминале WSL выполните проверки. Для повторной демонстрации очистите только запись для Москвы.

```bash
BASE=http://127.0.0.1:8083
curl -fsS "$BASE/" | python3 -m json.tool --no-ensure-ascii
curl -fsS "$BASE/health" | python3 -m json.tool --no-ensure-ascii
minikube -p lab5 kubectl -- exec deploy/yamaleeva-redis -- \
  redis-cli DEL 'weather:Ямалеева Азалия Фиразовна:moscow'
curl -fsS "$BASE/weather/Moscow" | python3 -m json.tool --no-ensure-ascii
curl -fsS "$BASE/weather/Moscow" | python3 -m json.tool --no-ensure-ascii
curl -fsS -H 'Content-Type: application/json' \
  -d '{"text":"ЛР5: проверка PostgreSQL"}' "$BASE/notes"
echo
curl -fsS "$BASE/notes" | python3 -m json.tool --no-ensure-ascii
```

Для отчёта снимите вывод `get pods`, `get svc,pvc`, имя владельца, ответ `/health`, приветствие с именем пода, оба ответа погоды, создание и чтение заметки, а также строки `Liveness`, `Readiness` и `Ready` из `describe pod`. В начале отчёта предусмотрен снимок образа, загруженного в Minikube.
