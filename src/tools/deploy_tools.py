#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""РЕЖИМ B — доставка правок в живую базу: deploy_module/dump_extension/deploy_extension_from_files/sync_extension_files."""
from src.tools.core import mcp, CFG, _spawn
from src.onec.module_deploy import (deploy_common_module as _deploy_module,
                                     deploy_main_common_module as _deploy_main_common_module)
from src.onec.extension_deploy import (deploy_extension_from_files as _deploy_extension_from_files,
                               sync_extension_files as _sync_extension_files,
                               dump_extension as _dump_extension,
                               adopt_object as _adopt_object,
                               deploy_http_service as _deploy_http_service,
                               adopt_form as _adopt_form)


@mcp.tool()
def deploy_module(ib_connection: str, ext_name: str, module_name: str, bsl_code: str,
                   synonym: str = "", client: bool = False, kill_sessions: bool = True) -> dict:
    """
    АСИНХРОННО (см. HANDOFF.md #25 п.5-6: DumpConfigToFiles/UpdateDBCfg на тяжёлой
    конфигурации регулярно дольше клиентского MCP-таймаута — теперь job_id вместо
    гадания по таймауту). Возвращает job_id СРАЗУ, результат — job_status(job_id)
    (обычно 10-90с, на тяжёлых конфигурациях может быть больше — просто подождите
    и переспросите job_status, не запускайте второй deploy_module параллельно в
    то же расширение — dump_lock всё равно откажет, но лишний вызов не нужен).

    РЕЖИМ B: создаёт/обновляет ОБЩИЙ МОДУЛЬ (не заимствованный) внутри
    расширения ext_name с текстом bsl_code (бизнес-логика ИЛИ тестовый модуль
    YaXUnit — механика одна и та же). Один вызов = вся правка "по файлам"
    (DumpConfigToFiles -> XML/BSL -> LoadConfigFromFiles -> UpdateDBCfg),
    руками лезть в файлы не нужно. Перед написанием тестового модуля вызови
    get_guide("yaxunit_tests") — там конвенции регистрации/assертов и
    известные грабли (например, ЮТест.Данные().СоздатьДокумент() возвращает
    Ссылку, для заполнения ТЧ нужен КонструкторОбъекта).

    НОВЫЙ модуль по умолчанию создаётся ЧИСТО СЕРВЕРНЫМ (Server=true,
    ClientManagedApplication/ClientOrdinaryApplication=false) — это критично для
    YaXUnit-тестов (ДобавитьСерверныйТест) и серверной бизнес-логики: модуль,
    отмеченный ОДНОВРЕМЕННО клиентским и серверным, может не резолвить вызовы
    других чисто серверных общих модулей в серверном контексте выполнения теста
    ("Переменная не определена") — поймано вживую, см. #24. Если такая ошибка
    всё же возникла — сверьтесь через describe_common_module. client=True —
    только если модулю реально нужен клиентский контекст.
    Результат (через job_status) может содержать "duplicate_warning" — то же имя
    уже встречалось в другом расширении (см. #25 п.7) — разберитесь, прежде чем
    продолжать. После завершения форма-раннер на этой базе закрыта (kill_sessions) —
    если дальше нужен run_module/warmup, подними её через start_runner.
    """
    jid = _spawn(_deploy_module, CFG, ib_connection, ext_name, module_name, bsl_code,
                 synonym=synonym, client=client, kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-90с (тяжёлая конфигурация — дольше)"}


@mcp.tool()
def deploy_main_common_module(ib_connection: str, module_name: str, bsl_code: str,
                               synonym: str = "", server: bool = True, client: bool = False,
                               kill_sessions: bool = True) -> dict:
    """
    АСИНХРОННО — см. deploy_module про job_id/job_status и почему.

    Создаёт/обновляет общий модуль ПРЯМО В ОСНОВНОЙ конфигурации (НЕ внутри
    расширения — для расширения используйте deploy_module). Формат XML
    подтверждён реальным дампом ERP АПК (CommonModules/ZipАрхивы.xml) —
    структура полностью совпадает с общим модулем расширения, отличий в теге
    нет. Механика идентична deploy_module (dump -> XML/BSL -> kill_sessions ->
    load -> update), но БЕЗ -Extension — весь ход в основной конфигурации.

    НОВЫЙ модуль по умолчанию чисто серверный (Server=true,
    ClientManagedApplication/ClientOrdinaryApplication=false) — см. deploy_module
    про то, почему это важно для YaXUnit-тестов и серверной бизнес-логики.
    После завершения форма-раннер на этой базе закрыта (kill_sessions) — если
    дальше нужен run_module/warmup, подними её через start_runner.
    """
    jid = _spawn(_deploy_main_common_module, CFG, ib_connection, module_name, bsl_code,
                 synonym=synonym, server=server, client=client, kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-90с (тяжёлая конфигурация — дольше)"}


@mcp.tool()
def dump_extension(ib_connection: str, ext_name: str) -> dict:
    """
    РЕЖИМ B, ТОЛЬКО ЧТЕНИЕ, синхронно (Dump не эксклюзивен — обычно секунды-минуты
    даже на тяжёлой конфигурации, раннер не трогает). Свежий DumpConfigToFiles
    расширения ext_name -> возвращает ЛОКАЛЬНЫЙ ПУТЬ (runtime/ext_src/ext_name).

    Нужен, когда пользователь НЕ дал путь к уже выгруженному дампу расширения на
    диске (в отличие от, например, Desktop\\vkr\\Расширение в этой сессии) — не
    нужно ждать/просить: выгрузите сами через dump_extension, затем читайте/
    грепайте файлы обычным Read/Grep. Тот же managed-каталог, что использует
    deploy_module/sync_extension_files — можно потом сразу sync_extension_files
    в тот же ext_name без повторного дампа.
    """
    return _dump_extension(CFG, ib_connection, ext_name)


@mcp.tool()
def deploy_extension_from_files(ib_connection: str, ext_root: str, ext_name: str,
                                 kill_sessions: bool = True) -> dict:
    """
    АСИНХРОННО — см. deploy_module про job_id/job_status и почему.

    РЕЖИМ B: доставляет ПРАВКИ РАСШИРЕНИЯ С ДИСКА (папка-дамп DumpConfigToFiles,
    например Desktop\\vkr\\Расширение — корень с Configuration.xml расширения)
    в базу ib_connection ЦЕЛИКОМ (LoadConfigFromFiles -Extension -> UpdateDBCfg,
    раздельными вызовами). Нужен, когда правки вносились прямыми Read/Edit по
    .bsl-файлам дампа, а не через deploy_module (один общий модуль). ОСТОРОЖНО на
    больших конфигурациях — см. #25 про рассинхрон версии формата у нетронутых
    файлов; для точечных правок используйте sync_extension_files.
    ext_root — КОРЕНЬ дампа расширения, не путь к отдельному модулю.
    После завершения форма-раннер на этой базе закрыта (kill_sessions,
    интерактивные сессии человека — не трогает) — если дальше нужен
    run_module/warmup, подними её через start_runner.
    """
    jid = _spawn(_deploy_extension_from_files, CFG, ib_connection, ext_root, ext_name,
                 kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~30-180с (весь дамп расширения — небыстро)"}


@mcp.tool()
def sync_extension_files(ib_connection: str, ext_name: str, writes: dict = None,
                          deletes: list = None, ensure_registered: list = None,
                          kill_sessions: bool = True) -> dict:
    """
    АСИНХРОННО — см. deploy_module про job_id/job_status и почему.

    РЕЖИМ B: точечная синхронизация ПРОИЗВОЛЬНЫХ файлов внутри УЖЕ существующего
    расширения ext_name — замена одноразовым Python-скриптам поверх
    DumpConfigToFiles/LoadConfigFromFiles (см. HANDOFF.md: паттерн повторялся
    вручную минимум дважды за сессию — правка ObjectModule.bsl обработки и
    удаление общего модуля).

    writes  — {относительный_путь_в_дампе: новое_содержимое}, например
              "DataProcessors/vkr_Поиск/Ext/ObjectModule.bsl": "<bsl-код>".
              Файл создаётся/перезаписывается. НЕ создаёт XML-регистрацию
              НОВОГО общего модуля — для этого используйте deploy_module.
              Для НОВОГО top-level объекта (например Adopted — см.
              adopt_object) используйте ensure_registered ниже.
    deletes — [относительный_путь_в_дампе, ...]. Для "CommonModules/Имя" или
              "CommonModules/Имя.xml" ДОПОЛНИТЕЛЬНО убирает
              <CommonModule>Имя</CommonModule> из ChildObjects Configuration.xml
              (иначе конфигурация будет ссылаться на удалённые файлы — именно
              так однажды получился дубль модуля с одинаковым именем в двух
              расширениях). Для остальных видов объектов метаданных
              автоправка тега НЕ выполняется — придёт tag_warnings.
    ensure_registered — [{"kind": "Document", "name": "Имя"}, ...] — идемпотентно
              добавляет <Kind>Имя</Kind> в ChildObjects корневого
              Configuration.xml РАСШИРЕНИЯ, если ещё нет. Нужен вместе с writes
              при добавлении НОВОГО top-level объекта (sync_extension_files сам
              XML для writes не строит, только применяет то, что дали).

    Пайплайн: свежий DumpConfigToFiles -> применить writes/deletes на диске ->
    kill_sessions (protect_interactive, интерактивные сессии человека не трогает) ->
    LoadConfigFromFiles -> UpdateDBCfg (раздельными вызовами).
    """
    jid = _spawn(_sync_extension_files, CFG, ib_connection, ext_name, writes=writes,
                 deletes=deletes, ensure_registered=ensure_registered, kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-90с (тяжёлая конфигурация — дольше)"}


@mcp.tool()
def adopt_object(ib_connection: str, ext_name: str, kind: str, name: str,
                  extended_configuration_object: str, kill_sessions: bool = True) -> dict:
    """
    АСИНХРОННО — см. deploy_module про job_id/job_status и почему.

    РЕЖИМ B: "пустое" ЗАИМСТВОВАНИЕ (Adopted) объекта БАЗОВОЙ конфигурации
    расширением ext_name — помечает объект kind/name базы известным расширению
    (ObjectBelonging=Adopted + ExtendedConfigurationObject), БЕЗ добавления кода
    в его модуль. Подтверждено реальными дампами (runtime/ext_src/vkrHttpService:
    Documents/АпкЖурналНадояМолока.xml, Catalogs/Пользователи.xml) — для таких
    объектов Ext-подпапка в дампе отсутствует, значит только формальная пометка,
    не расширение кода модуля.

    kind — ТОЛЬКО "Document" или "Catalog" (единственные подтверждённые виды).
    Для остальных видов метаданных формат Adopted НЕ проверен реальным
    примером — не угадывайте, получите дамп (Конфигуратор "Добавить" на
    объекте -> dump_extension) и сверьтесь, прежде чем расширять.
    name — имя объекта БАЗОВОЙ конфигурации (как в базе).
    extended_configuration_object — uuid объекта В БАЗОВОЙ конфигурации
    (найдите через dump_main_config -> read_reference_snippet/Grep по
    Documents/Catalogs/<Имя>.xml, атрибут uuid корневого тега).

    ВАЖНО: добавление РАСШИРЯЮЩЕГО кода в модуль заимствованного объекта
    (borrowed-module extension) этим тулом НЕ поддержано — ни одного реального
    примера такого XML/BSL не найдено в этой сессии, см. build_adopted_object_xml.
    """
    jid = _spawn(_adopt_object, CFG, ib_connection, ext_name, kind, name,
                 extended_configuration_object, kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-90с"}


@mcp.tool()
def adopt_form(ib_connection: str, ext_name: str, kind: str, doc_name: str,
                doc_extended_configuration_object: str, form_name: str,
                form_extended_configuration_object: str, base_form_body: str, bsl_code: str,
                command_overrides: list = None, kill_sessions: bool = True) -> dict:
    """
    АСИНХРОННО — см. deploy_module про job_id/job_status и почему.

    РЕЖИМ B: заимствование ФОРМЫ объекта базовой конфигурации С ПЕРЕХВАТОМ
    МЕТОДОВ — прямое продолжение adopt_object, подтверждено реальным дампом
    (Расширение1/Documents/ПриходнаяНакладная — пользователь добавил в
    Конфигураторе 4 метода перехвата на форме документа и дал посмотреть).

    Что делает одним вызовом: (1) помечает документ Adopted (если ещё не
    заимствован — создаёт; если уже — только добавляет form_name в его
    ChildObjects, не трогая другие уже заимствованные формы); (2) пишет
    дескриптор заимствованной формы; (3) пишет Ext/Form.xml (BaseForm-снимок
    оригинала + переопределение УЖЕ существующих команд через callType);
    (4) пишет Ext/Form/Module.bsl = bsl_code; (5) регистрирует документ в
    расширении, если ещё не был заимствован.

    kind — ТОЛЬКО "Document"/"Catalog". doc_name/form_name — имена КАК В
    БАЗОВОЙ конфигурации. doc_extended_configuration_object/
    form_extended_configuration_object — uuid ДОКУМЕНТА и uuid ФОРМЫ в базовой
    конфигурации (dump_main_config -> Read нужных .xml, атрибут uuid
    корневого тега).

    base_form_body — СЫРОЕ содержимое РЕАЛЬНОЙ базовой формы МЕЖДУ тегами
    <Form ...> и </Form> (AutoTime/ChildItems/Attributes/Commands) — возьмите
    из dump_main_config -> Read файла Documents/{Документ}/Forms/{Форма}/Ext/
    Form.xml БАЗОВОЙ конфигурации. Этот тул НЕ реконструирует вёрстку формы —
    заимствование работает поверх УЖЕ существующей формы, копируйте её текст.

    command_overrides — [{"name": "ИмяКоманды", "call_type": "Before"/"After",
    "handler": "ИмяBSL-процедуры"}, ...] — переопределяет <Action> УЖЕ
    существующей команды формы (найденной по name в base_form_body). НЕ
    добавляет новую команду — ValueError (вернётся как {"ok": false,
    "step": "build_borrowed_form_xml", ...}), если имя не найдено.

    bsl_code — ПОЛНЫЙ текст Ext/Form/Module.bsl: процедуры/функции с
    аннотациями &Перед("Имя")/&После("Имя")/&Вместо("Имя")/
    &ИзменениеИКонтроль("Имя") — ЭТИ перехваты (в отличие от command_overrides)
    НЕ требуют никакой правки Form.xml, только BSL — 1С сама резолвит имя
    базовой процедуры/функции по аргументу аннотации. Внутри &Вместо
    используйте ПродолжитьВызов(...) для вызова оригинала (подтверждено
    реальным примером: Функция Расш1_ПолучитьТекстДвижений(Ссылка) с
    &Вместо("ПолучитьТекстДвижений") и Результат = ПродолжитьВызов(Ссылка)).
    """
    jid = _spawn(_adopt_form, CFG, ib_connection, ext_name, kind, doc_name,
                 doc_extended_configuration_object, form_name, form_extended_configuration_object,
                 base_form_body, bsl_code, command_overrides=command_overrides,
                 kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-90с"}


@mcp.tool()
def deploy_http_service(ib_connection: str, ext_name: str, name: str, synonym: str,
                         root_url: str, url_templates: list, bsl_code: str,
                         reuse_sessions: str = "AutoUse", session_max_age: int = 20,
                         kill_sessions: bool = True) -> dict:
    """
    АСИНХРОННО — см. deploy_module про job_id/job_status и почему.

    РЕЖИМ B: создаёт/ЦЕЛИКОМ перезаписывает HTTPService name внутри расширения
    ext_name (адрес /<publication>/hs/{root_url}/...). Формат подтверждён
    ЕДИНСТВЕННЫМ реальным примером в этой сессии (runtime/ext_src/vkrHttpService/
    HTTPServices/vkr_ОсновнойСервис.xml).

    url_templates — [{"name": ..., "template": "/путь", "methods": [
        {"name": ..., "http_method": "GET"/"POST"/"PUT"/"PATCH"/"DELETE",
         "handler": "ИмяЭкспортнойФункцииВМодуле"}, ...]}, ...] — см.
    build_http_service_xml (extension_deploy.py) за полным описанием опциональных
    полей (synonym/comment).
    bsl_code — ПОЛНЫЙ текст Ext/Module.bsl: экспортные функции с именами из
    url_templates[].methods[].handler, каждая вида
    "Функция Имя(Запрос) Экспорт ... КонецФункции" — БИЗНЕС-ЛОГИКА внутри
    специфична для вашей задачи (см. реальный Module.bsl vkrHttpService как
    пример стиля, не как готовый шаблон).

    ВНИМАНИЕ: url_templates — ПОЛНАЯ замена (как deploy_catalog/deploy_document) —
    при обновлении СУЩЕСТВУЮЩЕГО сервиса передайте ВЕСЬ желаемый список
    (существующие url_templates, которые нужно сохранить, + новые), иначе
    отсутствующие в списке будут УДАЛЕНЫ. Корневой uuid сервиса при обновлении
    сохраняется автоматически (_preserve_existing_ids); uuid отдельных
    URLTemplate/Method — нет (не критично, ничего в конфигурации на них по uuid
    не ссылается).
    После завершения форма-раннер на этой базе закрыта (kill_sessions) — если
    дальше нужен run_module/warmup, подними её через start_runner.
    """
    jid = _spawn(_deploy_http_service, CFG, ib_connection, ext_name, name, synonym,
                 root_url, url_templates, bsl_code, reuse_sessions=reuse_sessions,
                 session_max_age=session_max_age, kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-90с (тяжёлая конфигурация — дольше)"}
