# Воспроизводимый локальный запуск и политика данных

## Проверяемый путь из чистого checkout

Будущая реализация MUST предоставить root README и tools/bootstrap.ps1, а также кроссплатформенный CLI `uv run alfalab`. Эти файлы пока являются результатами задач плана, а не уже работающими командами.

Prerequisites: Git, pinned Python/uv/Node/npm из toolchain manifest, Docker с Compose для PostgreSQL. Bootstrap проверяет версии и свободные loopback ports, создаёт .local, генерирует отдельные Development/Testing tokens и DB credentials без печати значений, запускает PostgreSQL, ставит dependencies из locks, выполняет миграции и seed. Секреты сохраняются только в .local с ограниченными правами; .local игнорируется Git.

Документированная процедура после реализации:

1. git clone/checkout; прочитать root README и toolchain manifest.
2. PowerShell: `./tools/bootstrap.ps1 -Profile development`.
3. `uv run alfalab doctor --profile development` — версии, DB roles/schema, hashes, registry count, отсутствие production configuration.
4. `uv run alfalab fixtures seed --dataset radio-export-v1 --sandbox demo-a` — идемпотентный seed только разрешённого sandbox.
5. `uv run alfalab serve --profile development` — API 127.0.0.1:8000; frontend отдельный `npm --prefix apps/playground run dev -- --host 127.0.0.1` на 5173.
6. Открыть Playground, локально прочитать developer token из .local по инструкции (token не печатается автоматическими logs), выполнить Documents.prepare и сквозной сценарий.
7. `uv run alfalab smoke --profile testing` — все 25 endpoints на test fixtures, strict replay и basic isolation.
8. `uv run alfalab scenario run document-business-impact --version 1.0.0 --dataset radio-export-v1 --profile development --implementation-profile mixed --stop-after <step>`; продолжение `scenario resume --run <id> --profile development`.

Server profile выбирает environment/resources; implementation-profile выбирает согласованный набор algorithms, не повышая права. Default API ports: development=8000, testing=8001, UI=5173. Smoke --profile testing поднимает временный test API на 8001, если его ещё нет, проверяет profile/build handshake и завершает только созданный им процесс. При занятом порте другого профиля — ошибка, не подключение к неизвестному API. Тестовый CLI seed/reset не использует Development DSN.

Повтор bootstrap не уничтожает данные. Reset отдельный: `alfalab sandbox reset --sandbox <id> --profile testing`; CLI проверяет resolved path/DB name/permissions и не работает с production. CI создаёт новую test DB и удаляет только проверенный именованный sandbox. Прерывание установки даёт понятный safe error и повторяемый шаг.

Чистая машина не требует API ключей моделей. Все default egress зависимости выключены; Sources использует fixture adapter, real.prepare работает локально. Live adapters включаются вручную серверным профилем после регистрации и тестов.

## Классификация и независимые права

| Категория | Локальная обработка | External model | Full record | Export/Git |
|---|---|---|---|---|
| утверждённая synthetic fixture | разрешена | только allowlisted adapter | разрешён | после scan/review |
| разрешённый public source | разрешена | по source/profile policy | по source/profile policy | по reuse policy + scan/review |
| manual/unknown | разрешена только ephemeral local implementation | запрещена | запрещён; безопасные metadata | запрещён |
| известные closed/secret | блокируется в первом каркасе | запрещена | запрещён | запрещён |

data_declaration — заявление клиента, не разрешение. Trusted classification определяется registered sources/approved fixtures и provenance verification. Manual synthetic declaration без trusted fixture manifest не превращает происхождение в verified. Для сохранения нового ручного synthetic experiment локальный developer review CLI создаёт разрешённый dataset manifest с reviewer identity; это tooling, не новый public operation. Он не утверждает gold expected result. Запись разрешения и hash входит в run policy decisions.

Policy проверяется до dependency egress и до любой записи содержимого. Raw request/response logging FastAPI/HTTPX/SDK выключен. Access logs содержат только safe IDs/status/latency. Validation errors очищены от rejected values. Provider error body хранить нельзя без классификации и фильтрации. Secret headers полностью исключены из cassette/hash material; request semantic identity не зависит от credential bytes.

Metadata-only run не содержит raw text/error echo, output artifacts или тайно сериализованного prompt. UI сообщает replay unavailable. Запрет записи не означает разрешение external передачи.

## Секреты и изоляция

Development, Testing и future Production используют разные credentials и resources. Local profiles не содержат production DSN/token. Principal фиксирует tenant, role и allowed sandboxes; client sandbox_id только выбирает разрешённый sandbox. Server config не импортируется из experiment bundle. SourceRequest имеет source_id, а не произвольный URL; source adapter URL allowlist проверяется с защитой от redirects к запрещённым адресам.

Приёмка: malicious environment/DSN/extra fields отклонены; чужой sandbox/ref недоступен; canary credential не обнаруживается в Git/logs/traces/cassettes/download; external gateway не вызывается для unknown/forbidden data. Automated scan не является доказательством отсутствия любых чувствительных сведений; каркас сознательно ограничен подготовленными разрешёнными наборами.

## Артефакты и retention

По умолчанию .local данные локальны и не публикуются. Manifest хранит retention class development_ephemeral|approved_fixture. Очистка ephemeral — отдельный CLI по scoped refs; никаких автоматических recursive deletes arbitrary paths. Утверждённые fixtures immutable по hash; смена данных создаёт новую version. Конкретная production retention/privacy policy отложена вместе с закрытыми данными.
