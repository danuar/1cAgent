#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Доставка ПРАВОК РАСШИРЕНИЯ С ДИСКА (папка-дамп DumpConfigToFiles, например
Desktop\\vkr\\Расширение) в указанную базу — целиком, а не один общий модуль
(это уже умеет deploy_module/module_deploy.py). Нужно, когда правки делаются
не через deploy_module построчно, а прямыми Read/Edit по .bsl-файлам дампа
(так дешевле по токенам для больших модулей — см. HANDOFF.md).

Синтаксис (два РАЗДЕЛЬНЫХ вызова — см. HANDOFF.md "Уроки": чейн одной строкой
один раз закатал старое содержимое модуля без ошибки в логе):
    1cv8.exe DESIGNER <connection> /LoadConfigFromFiles <ext_root> -Extension <Имя> /Out <log>
    1cv8.exe DESIGNER <connection> /UpdateDBCfg -Extension <Имя> /Out <log>

ext_root — КОРЕНЬ дампа расширения (папка, где лежит Configuration.xml самого
расширения, например Desktop\\vkr\\Расширение), НЕ путь к отдельному модулю.
"""
import re
import subprocess
import uuid
from pathlib import Path

from src.core.ib_connection import cli_connection_str
from src.onec.sessions import kill_matching_processes
from src.core.dump_lock import dump_lock
from src.core.xml_validate import validate_xml_files
from src.core.designer_log import read_designer_log
from src.onec.designer_run import run_watched, watched_error
from src.onec.metadata_deploy import (gen_internal_info, _NS, _FORM_NS, _TAG_BY_KIND, _FOLDER_BY_KIND,
                                       _preserve_existing_ids)


def _run(cmd: str, timeout: int, cfg: dict, ib_connection: str, step: str) -> tuple:
    """#45: обёртка над designer_run.run_watched — см. metadata_deploy.py для полного объяснения."""
    watched = run_watched(cmd, timeout, cfg, ib_connection)
    return watched["returncode"], watched_error(step, watched, timeout)


def dump_extension(cfg: dict, ib_connection: str, ext_name: str, timeout: int = 600) -> dict:
    """
    ТОЛЬКО ЧТЕНИЕ: свежий DumpConfigToFiles расширения ext_name в runtime/ext_src/<ext_name>
    и ВОЗВРАЩАЕТ ЛОКАЛЬНЫЙ ПУТЬ — читайте/грепайте его сами (Read/Grep), не нужно
    ждать, что пользователь уже держит где-то на диске ручной дамп конфигурации.
    Не требует kill_sessions (Dump не эксклюзивен) — раннер, если он был поднят,
    НЕ трогается. Тот же managed-каталог, что использует deploy_module/
    sync_extension_files — повторный вызов просто освежает его текущим состоянием БД.
    """
    try:
        conn = cli_connection_str(ib_connection)
    except ValueError as e:
        return {"ok": False, "step": "connection", "reason": str(e)}

    dump_dir = Path(cfg["runtime_dir"]) / "ext_src" / ext_name
    log_dir = Path(cfg["runtime_dir"]) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    with dump_lock(dump_dir):
        dump_log = log_dir / f"{ext_name}_readonly_dump.log"
        cmd_dump = (f'"{cfg["path_1c"]}" DESIGNER {conn} /DumpConfigToFiles "{dump_dir}" '
                    f'-Extension {ext_name} /Out "{dump_log}"')
        rc, watch_err = _run(cmd_dump, timeout, cfg, ib_connection, "DumpConfigToFiles")
        if watch_err:
            return watch_err
        if rc != 0:
            return {"ok": False, "step": "DumpConfigToFiles", "returncode": rc,
                    "log": read_designer_log(dump_log, tail=1500)}

        return {"ok": True, "path": str(dump_dir)}


# Папки дампа, для которых при удалении верхнеуровневого объекта (CommonModules/Имя[.xml])
# можно автоматически убрать регистрацию из Configuration.xml (ChildObjects). Ключ — имя
# папки дампа, значение — имя XML-тега в ChildObjects. Только "плоские" объекты одного
# уровня (общие модули) — не формы/макеты внутри объекта, у них другая структура.
_TOP_LEVEL_KIND_TAG = {
    "CommonModules": "CommonModule",
}


def sync_extension_files(cfg: dict, ib_connection: str, ext_name: str,
                          writes: dict = None, deletes: list = None,
                          ensure_registered: list = None,
                          kill_sessions: bool = True, timeout: int = 600) -> dict:
    """
    Универсальная синхронизация ПРОИЗВОЛЬНЫХ файлов внутри расширения ext_name —
    замена одноразовым Python-скриптам поверх DumpConfigToFiles/LoadConfigFromFiles
    (см. HANDOFF.md: этот паттерн повторялся вручную минимум дважды за сессию —
    правка ObjectModule.bsl обработки и удаление общего модуля).

    writes  — {относительный_путь_внутри_дампа: новое_содержимое}, например:
              "DataProcessors/vkr_Поиск/Ext/ObjectModule.bsl": "<bsl-код>"
              "CommonModules/vkr_Модуль/Ext/Module.bsl": "<bsl-код>"
              Файл создаётся (с родительскими папками) или перезаписывается.
              НЕ создаёт XML-регистрацию НОВОГО общего модуля — для этого используйте
              deploy_module (он сам генерирует CommonModules/<Имя>.xml + правит
              Configuration.xml). sync_extension_files — для УЖЕ существующих объектов
              или для файлов, не требующих отдельной XML-регистрации.
    deletes — [относительный_путь_внутри_дампа, ...] — файл или папка удаляются.
              Если путь имеет вид "CommonModules/Имя" или "CommonModules/Имя.xml" —
              ДОПОЛНИТЕЛЬНО убирает <CommonModule>Имя</CommonModule> из ChildObjects
              Configuration.xml (иначе конфигурация будет ссылаться на удалённые файлы).
              Для остальных видов объектов (Catalogs/Documents/...) тег ChildObjects
              НЕ трогается — если это не общий модуль, а целый объект метаданных,
              разберитесь с регистрацией руками (сложнее, там ещё Forms/Ext/Help и т.п.).
    ensure_registered — [{"kind": "Document", "name": "Имя"}, ...] — добавляет
              `<Kind>Имя</Kind>` в ChildObjects КОРНЕВОГО Configuration.xml
              РАСШИРЕНИЯ, если там ещё нет (идемпотентно). Нужен при добавлении
              НОВОГО top-level объекта через writes (например заимствованного
              (Adopted) объекта — см. adopt_object) — sync_extension_files сам
              XML для writes не генерирует, только применяет то, что дали.

    Пайплайн (как deploy_module): 1) свежий DumpConfigToFiles — источник истины БД;
    2) применить writes/deletes на диске; 3) kill_sessions (protect_interactive);
    4) LoadConfigFromFiles; 5) UpdateDBCfg — 4 и 5 РАЗДЕЛЬНЫМИ subprocess.run.
    """
    writes = writes or {}
    deletes = deletes or []
    try:
        conn = cli_connection_str(ib_connection)
    except ValueError as e:
        return {"ok": False, "step": "connection", "reason": str(e)}

    dump_dir = Path(cfg["runtime_dir"]) / "ext_src" / ext_name
    log_dir = Path(cfg["runtime_dir"]) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    with dump_lock(dump_dir):
        dump_log = log_dir / f"{ext_name}_sync_dump.log"
        cmd_dump = (f'"{cfg["path_1c"]}" DESIGNER {conn} /DumpConfigToFiles "{dump_dir}" '
                    f'-Extension {ext_name} /Out "{dump_log}"')
        rc, watch_err = _run(cmd_dump, timeout, cfg, ib_connection, "DumpConfigToFiles")
        if watch_err:
            return watch_err
        if rc != 0:
            return {"ok": False, "step": "DumpConfigToFiles", "returncode": rc,
                    "log": read_designer_log(dump_log, tail=1500)}

        applied_writes, applied_deletes, tag_warnings = [], [], []

        for rel_path, content in writes.items():
            target = dump_dir / Path(rel_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8-sig")
            applied_writes.append(rel_path)

        config_xml_path = dump_dir / "Configuration.xml"
        config_text = config_xml_path.read_text(encoding="utf-8-sig") if config_xml_path.exists() else None

        for rel_path in deletes:
            p = Path(rel_path)
            target = dump_dir / p
            if target.is_dir():
                import shutil
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                target.unlink()
            applied_deletes.append(rel_path)

            parts = p.parts
            if len(parts) >= 2 and parts[0] in _TOP_LEVEL_KIND_TAG:
                tag_name = _TOP_LEVEL_KIND_TAG[parts[0]]
                obj_name = Path(parts[1]).stem  # "Имя" из "Имя.xml" или "Имя" (папка)
                tag = f"\t\t\t<{tag_name}>{obj_name}</{tag_name}>\n"
                if config_text is not None and tag in config_text:
                    config_text = config_text.replace(tag, "")
                elif config_text is not None:
                    tag_warnings.append(f"тег {tag_name}>{obj_name} не найден в ChildObjects (уже отсутствовал?)")
            elif len(parts) >= 1:
                tag_warnings.append(f"{rel_path}: авто-правка ChildObjects не поддержана для этого вида объекта")

        registered_now = []
        if ensure_registered:
            if config_text is None:
                return {"ok": False, "step": "ensure_registered",
                        "reason": "не найден корневой Configuration.xml расширения"}
            anchor = "\n\t\t</ChildObjects>"
            if anchor not in config_text:
                return {"ok": False, "step": "ensure_registered",
                        "reason": "не найден ожидаемый </ChildObjects> в корневом Configuration.xml"}
            for item in ensure_registered:
                tag_name = _TAG_BY_KIND.get(item["kind"], item["kind"])
                child_tag = f"\t\t\t<{tag_name}>{item['name']}</{tag_name}>\n"
                if child_tag.strip() not in config_text:
                    config_text = config_text.replace(anchor, "\n" + child_tag + "\t\t</ChildObjects>", 1)
                    registered_now.append(item)

        if config_text is not None:
            config_xml_path.write_text(config_text, encoding="utf-8-sig")

        # XML-валидация ДО похода в DESIGNER — невалидный XML (например
        # неэкранированный "&" в тексте запроса) иначе не падает быстро с понятной
        # ошибкой, а вешает DESIGNER на минуты с пустым логом (см. xml_validate.py).
        touched_xml = [dump_dir / Path(p) for p in applied_writes] + ([config_xml_path] if config_text is not None else [])
        problems = validate_xml_files(touched_xml)
        if problems:
            return {"ok": False, "step": "xml_validate", "problems": problems,
                    "applied_writes": applied_writes, "applied_deletes": applied_deletes}

        kill_report = None
        if kill_sessions:
            kill_report = kill_matching_processes(ib_connection)

        load_log = log_dir / f"{ext_name}_sync_load.log"
        cmd_load = (f'"{cfg["path_1c"]}" DESIGNER {conn} /LoadConfigFromFiles "{dump_dir}" '
                    f'-Extension {ext_name} /Out "{load_log}"')
        rc, watch_err = _run(cmd_load, timeout, cfg, ib_connection, "LoadConfigFromFiles")
        if watch_err:
            return watch_err
        out_load = read_designer_log(load_log)
        if rc != 0:
            return {"ok": False, "step": "LoadConfigFromFiles", "returncode": rc, "log": out_load[-1500:],
                    "applied_writes": applied_writes, "applied_deletes": applied_deletes,
                    "kill_report": kill_report}

        update_log = log_dir / f"{ext_name}_sync_update.log"
        cmd_update = f'"{cfg["path_1c"]}" DESIGNER {conn} /UpdateDBCfg -Extension {ext_name} /Out "{update_log}"'
        rc, watch_err = _run(cmd_update, timeout, cfg, ib_connection, "UpdateDBCfg")
        if watch_err:
            return watch_err
        out_update = read_designer_log(update_log)
        if rc != 0:
            return {"ok": False, "step": "UpdateDBCfg", "returncode": rc, "log": out_update[-1500:],
                    "applied_writes": applied_writes, "applied_deletes": applied_deletes,
                    "kill_report": kill_report}

        return {"ok": True, "applied_writes": applied_writes, "applied_deletes": applied_deletes,
                "tag_warnings": tag_warnings, "registered_now": registered_now, "kill_report": kill_report}


_ADOPTABLE_KINDS = {"Document", "Catalog"}


def build_adopted_object_xml(kind: str, name: str, extended_configuration_object: str,
                              child_forms: list = None) -> str:
    """
    #46 (задача 3): "пустое" ЗАИМСТВОВАНИЕ (Adopted) объекта БАЗОВОЙ конфигурации
    расширением — подтверждено РЕАЛЬНЫМИ дампами runtime/ext_src/vkrHttpService
    (Documents/АпкЖурналНадояМолока.xml, Catalogs/Пользователи.xml): расширение
    формально ссылается на объект базовой конфигурации (ObjectBelonging=Adopted +
    ExtendedConfigurationObject=uuid объекта В БАЗОВОЙ конфигурации), но модуль
    объекта не трогает, своего кода в него не добавляет — Ext-подпапка для
    такого объекта в реальном дампе ОТСУТСТВУЕТ (проверено Glob).

    НЕ ПОДТВЕРЖДЕНО (честно, а не угадано): добавление РАСШИРЯЮЩЕГО кода в модуль
    заимствованного объекта (обычно через "&РасширениеОбработчика" в модуле-
    доноре + процедуру в Ext/ObjectModule.bsl заимствованного объекта) — ни
    одного реального примера с таким кодом не нашлось ни в vkrHttpService, ни
    где-либо ещё, доступном в этой сессии. Если реально понадобится ДОБАВИТЬ
    обработчик (а не просто пометить объект известным расширению) — следуйте
    правилу эскалации (get_guide): попросите пользователя вручную сделать в
    Конфигураторе "Добавить" на нужном объекте, затем dump_extension и сверьтесь
    с реальным Ext/-файлом, прежде чем обобщать в код.

    kind — ТОЛЬКО "Document" или "Catalog" (см. _ADOPTABLE_KINDS/adopt_object) —
    единственные виды, подтверждённые реальными дампами. RegisterRecords
    (пустой) добавляется только для Document — подтверждено тем же примером.

    child_forms — [ИмяФормы, ...] — список ЗАИМСТВОВАННЫХ форм ЭТОГО объекта
    (см. adopt_form/#52) — по умолчанию None/пусто -> `<ChildObjects/>`
    (самозакрывающийся, как в исходном "пустом" заимствовании); непустой
    список рендерит `<ChildObjects><Form>Имя</Form>...</ChildObjects>` —
    подтверждено реальным дампом (Расширение1/Documents/ПриходнаяНакладная.xml,
    предоставлен пользователем: `<ChildObjects><Form>ФормаДокумента</Form>
    </ChildObjects>`, а НЕ пустой, когда у документа есть заимствованная форма).
    ВАЖНО: передавайте ВСЕ уже заимствованные формы объекта + новую (если
    обновляете существующий Adopted-документ) — эта функция не читает диск
    сама, список — целиком на вызывающем (см. adopt_form, который это делает).
    """
    internal = gen_internal_info(kind, name)
    tag = _TAG_BY_KIND.get(kind, kind)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<MetaDataObject {_NS}>',
        f'\t<{tag} uuid="{uuid.uuid4()}">',
        internal,
        '\t\t<Properties>',
        '\t\t\t<ObjectBelonging>Adopted</ObjectBelonging>',
        f'\t\t\t<Name>{name}</Name>',
        '\t\t\t<Comment/>',
        f'\t\t\t<ExtendedConfigurationObject>{extended_configuration_object}</ExtendedConfigurationObject>',
    ]
    if kind == "Document":
        lines.append('\t\t\t<RegisterRecords/>')
    lines.append('\t\t</Properties>')
    if child_forms:
        lines.append('\t\t<ChildObjects>')
        for form_name in child_forms:
            lines.append(f'\t\t\t<Form>{form_name}</Form>')
        lines.append('\t\t</ChildObjects>')
    else:
        lines.append('\t\t<ChildObjects/>')
    lines += [
        f'\t</{tag}>',
        '</MetaDataObject>',
        '',
    ]
    return "\n".join(lines)


def adopt_object(cfg: dict, ib_connection: str, ext_name: str, kind: str, name: str,
                  extended_configuration_object: str, kill_sessions: bool = True, timeout: int = 600) -> dict:
    """
    "Пустое" ЗАИМСТВОВАНИЕ (Adopted) объекта БАЗОВОЙ конфигурации расширением
    ext_name — помечает объект kind/name базы известным расширению
    (ObjectBelonging=Adopted + ExtendedConfigurationObject), БЕЗ добавления кода
    в его модуль — см. build_adopted_object_xml про то, что подтверждено
    реальными примерами, а что нет.

    kind — ТОЛЬКО "Document" или "Catalog" (единственные подтверждённые виды —
    см. build_adopted_object_xml). Для остальных видов метаданных формат
    Adopted не проверен реальным примером — не угадывайте, сначала получите
    дамп (Конфигуратор "Добавить" -> dump_extension), потом расширяйте список.
    name — имя объекта БАЗОВОЙ конфигурации (как в базе, не придумывается).
    extended_configuration_object — uuid объекта В БАЗОВОЙ конфигурации
    (найдите через dump_main_config -> read_reference_snippet/Grep по
    Documents/Catalogs/<Имя>.xml, атрибут uuid корневого тега объекта).

    Тонкая обёртка над sync_extension_files: строит XML заимствования и
    передаёт его через writes + ensure_registered одним dump->load->update
    циклом, без ручной правки ChildObjects.
    """
    if kind not in _ADOPTABLE_KINDS:
        return {"ok": False, "step": "precheck",
                "reason": f"kind={kind} не подтверждён реальным примером Adopted — "
                          f"поддержаны только {sorted(_ADOPTABLE_KINDS)}"}

    folder = _FOLDER_BY_KIND[kind]
    xml_content = build_adopted_object_xml(kind, name, extended_configuration_object)
    return sync_extension_files(
        cfg, ib_connection, ext_name,
        writes={f"{folder}/{name}.xml": xml_content},
        ensure_registered=[{"kind": kind, "name": name}],
        kill_sessions=kill_sessions, timeout=timeout,
    )


_FORM_TAG_RE = re.compile(r'<Form>([^<]+)</Form>')


def build_adopted_form_descriptor_xml(form_name: str, extended_configuration_object: str) -> str:
    """
    #52 (задача 9): дескриптор ЗАИМСТВОВАННОЙ (Adopted) формы —
    Documents/{Документ}/Forms/{Форма}.xml ВНУТРИ расширения. Подтверждено
    РЕАЛЬНЫМ дампом, который добавил пользователь (runtime/ext_src/Расширение1/
    Documents/ПриходнаяНакладная/Forms/ФормаДокумента.xml): БЕЗ ChildObjects
    вообще (в отличие от обычного MetaDataObject-объекта), Properties содержит
    РОВНО ObjectBelonging/Name/Comment/ExtendedConfigurationObject/
    FormType=Managed — заметно ПРОЩЕ дескриптора НОВОЙ формы
    (metadata_deploy.build_form_descriptor_xml — тот для основной конфигурации,
    с Synonym/UsePurposes/IncludeHelpInContents, которых здесь НЕТ).

    extended_configuration_object — uuid САМОЙ ФОРМЫ в базовой конфигурации
    (НЕ путать с uuid документа) — найдите через dump_main_config + Read
    Documents/{Документ}/Forms/{Форма}.xml базовой конфигурации, атрибут uuid
    корневого тега <Form>.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<MetaDataObject {_NS}>\n'
        f'\t<Form uuid="{uuid.uuid4()}">\n'
        '\t\t<InternalInfo/>\n'
        '\t\t<Properties>\n'
        '\t\t\t<ObjectBelonging>Adopted</ObjectBelonging>\n'
        f'\t\t\t<Name>{form_name}</Name>\n'
        '\t\t\t<Comment/>\n'
        f'\t\t\t<ExtendedConfigurationObject>{extended_configuration_object}</ExtendedConfigurationObject>\n'
        '\t\t\t<FormType>Managed</FormType>\n'
        '\t\t</Properties>\n'
        '\t</Form>\n'
        '</MetaDataObject>\n'
    )


def build_borrowed_form_xml(base_form_body: str, command_overrides: list = None) -> str:
    """
    #52 (задача 9): Ext/Form.xml ЗАИМСТВОВАННОЙ формы — подтверждено реальным
    дампом Расширение1/Documents/ПриходнаяНакладная/Forms/ФормаДокумента/Ext/
    Form.xml (пользователь добавил в Конфигураторе 4 метода перехвата и дал
    Claude посмотреть). Структура: ВНЕШНЯЯ копия формы (правки расширения) +
    вложенный <BaseForm version="2.19"> — НЕТРОНУТЫЙ снимок ОРИГИНАЛЬНОЙ формы
    базовой конфигурации (судя по всему, для сверки платформой/Конфигуратором,
    что именно изменено).

    base_form_body — СЫРОЕ содержимое РЕАЛЬНОЙ базовой формы МЕЖДУ тегами
    <Form ...> и </Form> (AutoTime/ChildItems/Attributes/Commands и т.п.) —
    получите его через dump_main_config + Read реального файла
    Documents/{Документ}/Forms/{Форма}/Ext/Form.xml БАЗОВОЙ конфигурации. Этот
    тул НЕ реконструирует произвольную вёрстку формы с нуля (в отличие от
    metadata_deploy.build_document_form_xml для НОВЫХ форм) — заимствование по
    определению работает ПОВЕРХ уже существующей формы, скопировать её текст
    надёжнее, чем пытаться воспроизвести генератором (тот же принцип, что и
    у build_adopted_object_xml/adopt_object — не угадывать формат объекта,
    которого не создаём с нуля).

    command_overrides — [{"name": "ИмяКоманды", "call_type": "Before"/"After"/
    None, "handler": "ИмяВашейBSL-процедуры"}, ...] — команда С ЭТИМ ИМЕНЕМ
    ДОЛЖНА УЖЕ существовать в base_form_body (подтверждённый паттерн —
    переопределяется <Action> УЖЕ существующей команды через
    callType="Before"/"After", а НЕ добавляется новая команда: новая
    потребовала бы ещё и нового элемента формы, который её вызывает — такой
    случай НЕ подтверждён реальным примером, не реализован). call_type=None —
    редкий случай замены Action БЕЗ атрибута callType (не встречен в реальном
    примере, оставлен для гибкости, но НЕ подтверждён). ValueError, если
    команда с таким именем не найдена в base_form_body — не угадываем силой.

    ВНИМАНИЕ (что НЕ покрыто, честно): перехват процедур/функций ПО ИМЕНИ
    (&Перед/&После/&Вместо/&ИзменениеИКонтроль в Module.bsl, НЕ привязанных к
    UI-команде — например Расш1_ТоварыЦенаПриИзменении на &ИзменениеИКонтроль
    ОБРАБОТЧИКА ПОЛЯ, не команды) НЕ требует правки Form.xml вообще — это
    делается ТОЛЬКО в BSL-модуле (см. adopt_form: bsl_code пишете сами, эта
    функция XML для АННОТАЦИЙ В МОДУЛЕ не строит и не проверяет — 1С сама
    резолвит имя базовой процедуры/функции по аргументу аннотации при
    LoadConfigFromFiles/UpdateDBCfg).

    ГРАБЛЯ (найдена ЖИВЬЮМ, #55): если base_form_body содержит ЯВНЫЕ теги
    <DataPath>Объект.Поле</DataPath> у полей/таблиц (некоторые дампы форм их
    пишут явно, некоторые — нет, платформа умеет и без них автобиндить по
    совпадению имени поля с именем реквизита) — LoadConfigFromFiles падает с
    диалогом "Неверный путь к данным: ..." ИМЕННО в контексте ЗАИМСТВОВАННОЙ
    (borrowed) формы, хотя ТА ЖЕ разметка с теми же DataPath прекрасно
    работает как обычная форма основной конфигурации (проверено вживую на
    TestDB15/РасходнаяНакладная — 12 ошибок "Неверный путь к данным" на explicit
    DataPath, LoadConfigFromFiles провалился с модальным диалогом, run_watched
    поймал и убил процесс; после УДАЛЕНИЯ строк `<DataPath>...</DataPath>` из
    base_form_body — тот же вызов прошёл успешно). Похоже, в момент валидации
    ОДНОГО файла заимствованной формы внутри общего LoadConfigFromFiles
    расширения типизация ChildItems ЗАИМСТВОВАННОГО документа (табличные части
    и т.п.) ещё не полностью резолвится для явных DataPath — если base_form_body
    берёте из РЕАЛЬНОГО дампа и он падает с такой ошибкой, попробуйте убрать
    строки `<DataPath>...</DataPath>` (автобиндинг по имени поля возьмёт на
    себя разрешение пути) — это НЕ меняет, какие данные показывает поле, лишь
    КАК путь резолвится. Подтверждённый реальный пример (ПриходнаяНакладная,
    добавленный пользователем) изначально DataPath вообще не содержал.
    """
    outer_body = base_form_body
    for ov in (command_overrides or []):
        name = ov["name"]
        call_type = ov.get("call_type")
        handler = ov["handler"]
        action_tag = f'<Action callType="{call_type}">{handler}</Action>' if call_type else f'<Action>{handler}</Action>'
        pattern = re.compile(
            rf'(<Command name="{re.escape(name)}"[^>]*>.*?)<Action[^>]*>[^<]*</Action>(.*?</Command>)',
            re.DOTALL)
        new_body, n = pattern.subn(lambda m: m.group(1) + action_tag + m.group(2), outer_body, count=1)
        if n == 0:
            raise ValueError(f'команда "{name}" не найдена в base_form_body — command_overrides '
                              f'переопределяют ТОЛЬКО уже существующие команды базовой формы, '
                              f'новую команду этот тул не добавляет (см. докстринг)')
        outer_body = new_body

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<Form {_FORM_NS}>\n'
        f'{outer_body}\n'
        '\t<BaseForm version="2.19">\n'
        f'{base_form_body}\n'
        '\t</BaseForm>\n'
        '</Form>\n'
    )


def adopt_form(cfg: dict, ib_connection: str, ext_name: str, kind: str, doc_name: str,
                doc_extended_configuration_object: str, form_name: str,
                form_extended_configuration_object: str, base_form_body: str, bsl_code: str,
                command_overrides: list = None, kill_sessions: bool = True, timeout: int = 600) -> dict:
    """
    #52 (задача 9): заимствование ФОРМЫ объекта базовой конфигурации с
    перехватом методов — прямое продолжение adopt_object по реальному примеру,
    который добавил пользователь (Расширение1/Documents/ПриходнаяНакладная,
    4 метода перехвата на форме документа). Делает ОДНИМ вызовом:
      1. Помечает документ kind/doc_name базы Adopted (если ещё не помечен —
         создаёт; если уже — сохраняет существующий uuid/InternalInfo через
         _preserve_existing_ids, ТОЛЬКО добавляет form_name в его
         ChildObjects, не трогая уже заимствованные формы этого документа).
      2. Пишет дескриптор заимствованной формы (build_adopted_form_descriptor_xml).
      3. Пишет Ext/Form.xml (build_borrowed_form_xml — BaseForm-обёртка +
         переопределение существующих команд).
      4. Пишет Ext/Form/Module.bsl = bsl_code (аннотированные процедуры —
         &Перед/&После/&Вместо/&ИзменениеИКонтроль — пишете сами, см.
         build_borrowed_form_xml докстринг про то, что это НЕ требует правки
         Form.xml).
      5. Регистрирует <Document>doc_name</Document> в корневом ChildObjects
         расширения, ЕСЛИ документ ещё не был заимствован раньше.

    kind — ТОЛЬКО "Document"/"Catalog" (см. _ADOPTABLE_KINDS). doc_name/
    form_name — имена КАК В БАЗОВОЙ конфигурации. doc_extended_configuration_object/
    form_extended_configuration_object — uuid ДОКУМЕНТА и uuid ФОРМЫ в базовой
    конфигурации (см. build_adopted_object_xml/build_adopted_form_descriptor_xml
    про то, где их взять — dump_main_config + Read).
    base_form_body/command_overrides/bsl_code — см. build_borrowed_form_xml.

    Собственный полный пайплайн (НЕ обёртка над sync_extension_files — нужно
    прочитать состояние ДО генерации XML, чтобы решить create-vs-update и
    собрать полный список уже заимствованных форм документа, та же причина,
    что и у deploy_http_service/deploy_main_common_module).
    """
    if kind not in _ADOPTABLE_KINDS:
        return {"ok": False, "step": "precheck",
                "reason": f"kind={kind} не подтверждён реальным примером Adopted — "
                          f"поддержаны только {sorted(_ADOPTABLE_KINDS)}"}
    try:
        conn = cli_connection_str(ib_connection)
    except ValueError as e:
        return {"ok": False, "step": "connection", "reason": str(e)}

    dump_dir = Path(cfg["runtime_dir"]) / "ext_src" / ext_name
    log_dir = Path(cfg["runtime_dir"]) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    with dump_lock(dump_dir):
        dump_log = log_dir / f"{ext_name}_form_adopt_dump.log"
        cmd_dump = (f'"{cfg["path_1c"]}" DESIGNER {conn} /DumpConfigToFiles "{dump_dir}" '
                    f'-Extension {ext_name} /Out "{dump_log}"')
        rc, watch_err = _run(cmd_dump, timeout, cfg, ib_connection, "DumpConfigToFiles")
        if watch_err:
            return watch_err
        if rc != 0:
            return {"ok": False, "step": "DumpConfigToFiles", "returncode": rc,
                    "log": read_designer_log(dump_log, tail=1500)}

        folder = _FOLDER_BY_KIND[kind]
        doc_xml_path = dump_dir / folder / f"{doc_name}.xml"
        doc_created = not doc_xml_path.exists()

        existing_forms = []
        old_doc_xml = None
        if not doc_created:
            old_doc_xml = doc_xml_path.read_text(encoding="utf-8-sig")
            existing_forms = _FORM_TAG_RE.findall(old_doc_xml)
        if form_name not in existing_forms:
            existing_forms = existing_forms + [form_name]

        doc_xml_text = build_adopted_object_xml(kind, doc_name, doc_extended_configuration_object,
                                                  child_forms=existing_forms)
        if old_doc_xml is not None:
            doc_xml_text = _preserve_existing_ids(doc_xml_text, old_doc_xml)
        doc_xml_path.parent.mkdir(parents=True, exist_ok=True)
        doc_xml_path.write_text(doc_xml_text, encoding="utf-8-sig")

        descriptor_path = dump_dir / folder / doc_name / "Forms" / f"{form_name}.xml"
        form_xml_path = dump_dir / folder / doc_name / "Forms" / form_name / "Ext" / "Form.xml"
        module_path = dump_dir / folder / doc_name / "Forms" / form_name / "Ext" / "Form" / "Module.bsl"

        descriptor_created = not descriptor_path.exists()
        old_descriptor_xml = descriptor_path.read_text(encoding="utf-8-sig") if not descriptor_created else None
        descriptor_xml = build_adopted_form_descriptor_xml(form_name, form_extended_configuration_object)
        if old_descriptor_xml is not None:
            descriptor_xml = _preserve_existing_ids(descriptor_xml, old_descriptor_xml)
        descriptor_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor_path.write_text(descriptor_xml, encoding="utf-8-sig")

        try:
            form_xml_text = build_borrowed_form_xml(base_form_body, command_overrides)
        except ValueError as e:
            return {"ok": False, "step": "build_borrowed_form_xml", "reason": str(e)}
        form_xml_path.parent.mkdir(parents=True, exist_ok=True)
        form_xml_path.write_text(form_xml_text, encoding="utf-8-sig")

        module_path.parent.mkdir(parents=True, exist_ok=True)
        module_path.write_text(bsl_code.lstrip("﻿"), encoding="utf-8-sig")

        config_xml_path = dump_dir / "Configuration.xml"
        doc_registered_now = False
        if doc_created:
            config_text = config_xml_path.read_text(encoding="utf-8-sig")
            tag_name = _TAG_BY_KIND.get(kind, kind)
            tag = f"\t\t\t<{tag_name}>{doc_name}</{tag_name}>\n"
            if tag.strip() not in config_text:
                target = "\n\t\t</ChildObjects>"
                if target not in config_text:
                    return {"ok": False, "step": "patch_childobjects",
                            "reason": "не найден ожидаемый </ChildObjects> расширения верхнего уровня — "
                                      "структура дампа неожиданная, правьте руками"}
                config_text = config_text.replace(target, "\n" + tag + "\t\t</ChildObjects>", 1)
                config_xml_path.write_text(config_text, encoding="utf-8-sig")
                doc_registered_now = True

        problems = validate_xml_files([doc_xml_path, descriptor_path, form_xml_path, config_xml_path])
        if problems:
            return {"ok": False, "step": "xml_validate", "problems": problems}

        kill_report = None
        if kill_sessions:
            kill_report = kill_matching_processes(ib_connection)

        load_log = log_dir / f"{ext_name}_form_adopt_load.log"
        cmd_load = (f'"{cfg["path_1c"]}" DESIGNER {conn} /LoadConfigFromFiles "{dump_dir}" '
                    f'-Extension {ext_name} /Out "{load_log}"')
        rc, watch_err = _run(cmd_load, timeout, cfg, ib_connection, "LoadConfigFromFiles")
        if watch_err:
            return watch_err
        out_load = read_designer_log(load_log)
        if rc != 0:
            return {"ok": False, "step": "LoadConfigFromFiles", "returncode": rc, "log": out_load[-1500:],
                    "doc_created": doc_created, "form_created": descriptor_created, "kill_report": kill_report}

        update_log = log_dir / f"{ext_name}_form_adopt_update.log"
        cmd_update = f'"{cfg["path_1c"]}" DESIGNER {conn} /UpdateDBCfg -Extension {ext_name} /Out "{update_log}"'
        rc, watch_err = _run(cmd_update, timeout, cfg, ib_connection, "UpdateDBCfg")
        if watch_err:
            return watch_err
        out_update = read_designer_log(update_log)
        if rc != 0:
            return {"ok": False, "step": "UpdateDBCfg", "returncode": rc, "log": out_update[-1500:],
                    "doc_created": doc_created, "form_created": descriptor_created, "kill_report": kill_report}

        return {"ok": True, "document": doc_name, "form": form_name, "extension": ext_name,
                "doc_created": doc_created, "form_created": descriptor_created,
                "doc_registered_now": doc_registered_now, "kill_report": kill_report}


def build_http_service_xml(name: str, synonym: str, root_url: str, url_templates: list,
                            reuse_sessions: str = "AutoUse", session_max_age: int = 20) -> str:
    """
    #48 (задача 5): HTTPService — подтверждено ЕДИНСТВЕННЫМ реальным примером,
    доступным в этой сессии: runtime/ext_src/vkrHttpService/HTTPServices/
    vkr_ОсновнойСервис.xml. БЕЗ InternalInfo (как Subsystem/CommonModule/Role) —
    платформенный объект, не порождает ссылочные типы.

    url_templates — [{"name": ..., "synonym": "необязательно, по умолчанию = name",
                       "template": "/путь", "comment": "необязательно",
                       "methods": [{"name": ..., "synonym": "необязательно",
                                    "comment": "необязательно",
                                    "http_method": "GET"/"POST"/"PUT"/"PATCH"/"DELETE",
                                    "handler": "ИмяЭкспортнойФункцииВМодуле"}, ...]}, ...]

    handler — имя ЭКСПОРТНОЙ функции в Ext/Module.bsl ЭТОГО HTTPService,
    принимающей один параметр (объект HTTP-запроса, Функция Х(Запрос)) и
    возвращающей HTTPСервисОтвет. Конкретные паттерны бизнес-логики внутри
    обработчика (см. реальный Module.bsl vkrHttpService — там своя обвязка
    через Обработки.vkr_Запись/vkr_Поиск) специфичны для проекта-донора
    примера, НЕ универсальны — пишите bsl_code сами под свою задачу.

    ПОЛНАЯ замена XML (как deploy_catalog/deploy_document) — передавайте ВЕСЬ
    желаемый список url_templates (существующие + новые), не только
    добавляемое. Корневой uuid HTTPService (и только он — вложенные
    URLTemplate/Method не хранят ссылающихся на них по uuid данных, в отличие
    от, например, атрибутов справочника) сохраняется через
    _preserve_existing_ids в deploy_http_service при обновлении существующего
    сервиса — не регенерируется этой функцией самой по себе (она не знает,
    новый это сервис или обновление).
    """
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<MetaDataObject {_NS}>',
        f'\t<HTTPService uuid="{uuid.uuid4()}">',
        '\t\t<Properties>',
        f'\t\t\t<Name>{name}</Name>',
        f'\t\t\t<Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>{synonym}</v8:content></v8:item></Synonym>',
        '\t\t\t<Comment/>',
        f'\t\t\t<RootURL>{root_url}</RootURL>',
        f'\t\t\t<ReuseSessions>{reuse_sessions}</ReuseSessions>',
        f'\t\t\t<SessionMaxAge>{session_max_age}</SessionMaxAge>',
        '\t\t</Properties>',
        '\t\t<ChildObjects>',
    ]
    for ut in url_templates:
        parts.append(f'\t\t\t<URLTemplate uuid="{uuid.uuid4()}">')
        parts.append('\t\t\t\t<Properties>')
        parts.append(f'\t\t\t\t\t<Name>{ut["name"]}</Name>')
        parts.append('\t\t\t\t\t<Synonym><v8:item><v8:lang>ru</v8:lang>'
                      f'<v8:content>{ut.get("synonym", ut["name"])}</v8:content></v8:item></Synonym>')
        ut_comment = ut.get("comment", "")
        parts.append(f'\t\t\t\t\t<Comment>{ut_comment}</Comment>' if ut_comment else '\t\t\t\t\t<Comment/>')
        parts.append(f'\t\t\t\t\t<Template>{ut["template"]}</Template>')
        parts.append('\t\t\t\t</Properties>')
        parts.append('\t\t\t\t<ChildObjects>')
        for m in ut.get("methods", []):
            parts.append(f'\t\t\t\t\t<Method uuid="{uuid.uuid4()}">')
            parts.append('\t\t\t\t\t\t<Properties>')
            parts.append(f'\t\t\t\t\t\t\t<Name>{m["name"]}</Name>')
            parts.append('\t\t\t\t\t\t\t<Synonym><v8:item><v8:lang>ru</v8:lang>'
                          f'<v8:content>{m.get("synonym", m["name"])}</v8:content></v8:item></Synonym>')
            m_comment = m.get("comment", "")
            parts.append(f'\t\t\t\t\t\t\t<Comment>{m_comment}</Comment>' if m_comment else '\t\t\t\t\t\t\t<Comment/>')
            parts.append(f'\t\t\t\t\t\t\t<HTTPMethod>{m["http_method"]}</HTTPMethod>')
            parts.append(f'\t\t\t\t\t\t\t<Handler>{m["handler"]}</Handler>')
            parts.append('\t\t\t\t\t\t</Properties>')
            parts.append('\t\t\t\t\t</Method>')
        parts.append('\t\t\t\t</ChildObjects>')
        parts.append('\t\t\t</URLTemplate>')
    parts += ['\t\t</ChildObjects>', '\t</HTTPService>', '</MetaDataObject>', '']
    return "\n".join(parts)


def deploy_http_service(cfg: dict, ib_connection: str, ext_name: str, name: str, synonym: str,
                         root_url: str, url_templates: list, bsl_code: str,
                         reuse_sessions: str = "AutoUse", session_max_age: int = 20,
                         kill_sessions: bool = True, timeout: int = 600) -> dict:
    """
    Создаёт (если нет) или ЦЕЛИКОМ перезаписывает (если есть — см.
    build_http_service_xml про "полная замена") HTTPService name внутри
    расширения ext_name, с текстом Module.bsl = bsl_code. Возвращает
    {"ok": bool, "created": bool, ...}.

    Собственный пайплайн (НЕ обёртка над sync_extension_files — нужно решить
    created ДО генерации XML, чтобы для СУЩЕСТВУЮЩЕГО сервиса сохранить
    корневой uuid через _preserve_existing_ids, как deploy_common_module/
    deploy_main_common_module делают для CommonModule): свежий
    DumpConfigToFiles -> собрать XML/BSL -> зарегистрировать в ChildObjects
    (если новый) -> kill_sessions -> LoadConfigFromFiles -> UpdateDBCfg
    (-Extension, раздельными вызовами).
    """
    try:
        conn = cli_connection_str(ib_connection)
    except ValueError as e:
        return {"ok": False, "step": "connection", "reason": str(e)}

    dump_dir = Path(cfg["runtime_dir"]) / "ext_src" / ext_name
    log_dir = Path(cfg["runtime_dir"]) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    with dump_lock(dump_dir):
        dump_log = log_dir / f"{ext_name}_http_dump.log"
        cmd_dump = (f'"{cfg["path_1c"]}" DESIGNER {conn} /DumpConfigToFiles "{dump_dir}" '
                    f'-Extension {ext_name} /Out "{dump_log}"')
        rc, watch_err = _run(cmd_dump, timeout, cfg, ib_connection, "DumpConfigToFiles")
        if watch_err:
            return watch_err
        if rc != 0:
            return {"ok": False, "step": "DumpConfigToFiles", "returncode": rc,
                    "log": read_designer_log(dump_log, tail=1500)}

        service_xml = dump_dir / "HTTPServices" / f"{name}.xml"
        service_bsl = dump_dir / "HTTPServices" / name / "Ext" / "Module.bsl"
        created = not service_xml.exists()

        xml_text = build_http_service_xml(name, synonym or name, root_url, url_templates,
                                           reuse_sessions=reuse_sessions, session_max_age=session_max_age)
        if not created:
            old_xml = service_xml.read_text(encoding="utf-8-sig")
            xml_text = _preserve_existing_ids(xml_text, old_xml)
        service_xml.parent.mkdir(parents=True, exist_ok=True)
        service_xml.write_text(xml_text, encoding="utf-8-sig")

        service_bsl.parent.mkdir(parents=True, exist_ok=True)
        service_bsl.write_text(bsl_code.lstrip("﻿"), encoding="utf-8-sig")

        config_xml = dump_dir / "Configuration.xml"
        text = config_xml.read_text(encoding="utf-8-sig")
        if created:
            tag = f"\t\t\t<HTTPService>{name}</HTTPService>\n"
            if tag not in text:
                target = "\n\t\t</ChildObjects>"
                if target not in text:
                    return {"ok": False, "step": "patch_childobjects", "created": created,
                            "reason": "не найден ожидаемый </ChildObjects> расширения верхнего уровня — "
                                      "структура дампа неожиданная, правьте руками"}
                text = text.replace(target, "\n" + tag + "\t\t</ChildObjects>", 1)
                config_xml.write_text(text, encoding="utf-8-sig")

        problems = validate_xml_files([service_xml, config_xml])
        if problems:
            return {"ok": False, "step": "xml_validate", "created": created, "problems": problems}

        kill_report = None
        if kill_sessions:
            kill_report = kill_matching_processes(ib_connection)

        load_log = log_dir / f"{ext_name}_http_load.log"
        cmd_load = (f'"{cfg["path_1c"]}" DESIGNER {conn} /LoadConfigFromFiles "{dump_dir}" '
                    f'-Extension {ext_name} /Out "{load_log}"')
        rc, watch_err = _run(cmd_load, timeout, cfg, ib_connection, "LoadConfigFromFiles")
        if watch_err:
            return watch_err
        out_load = read_designer_log(load_log)
        if rc != 0:
            return {"ok": False, "step": "LoadConfigFromFiles", "returncode": rc, "log": out_load[-1500:],
                    "created": created, "kill_report": kill_report}

        update_log = log_dir / f"{ext_name}_http_update.log"
        cmd_update = f'"{cfg["path_1c"]}" DESIGNER {conn} /UpdateDBCfg -Extension {ext_name} /Out "{update_log}"'
        rc, watch_err = _run(cmd_update, timeout, cfg, ib_connection, "UpdateDBCfg")
        if watch_err:
            return watch_err
        out_update = read_designer_log(update_log)
        if rc != 0:
            return {"ok": False, "step": "UpdateDBCfg", "returncode": rc, "log": out_update[-1500:],
                    "created": created, "kill_report": kill_report}

        return {"ok": True, "created": created, "service": name, "extension": ext_name,
                "kill_report": kill_report}


def deploy_extension_from_files(cfg: dict, ib_connection: str, ext_root: str, ext_name: str,
                                 timeout: int = 600, kill_sessions: bool = True) -> dict:
    """
    Загружает КОРЕНЬ ext_root (дамп расширения с диска, Configuration.xml + все
    объекты) в базу ib_connection под именем ext_name, поверх уже существующего
    там расширения. Возвращает {"ok": bool, "step": "...", ...}.

    kill_sessions=True (по умолчанию) — перед UpdateDBCfg завершает СОБСТВЕННЫЕ
    автоматизированные сессии 1cAgent на этой базе (форма-раннер); интерактивные
    сессии человека (Конфигуратор/клиент, открытые вручную) НЕ трогает —
    protect_interactive в kill_matching_processes (см. sessions.py).

    Без dump_lock — ext_root ВНЕШНИЙ путь (например Desktop\\vkr\\Расширение), не
    наша managed-папка runtime/ext_src/<ext>, гонки конкурентных вызовов сюда не
    актуальны так же, как для sync_extension_files/deploy_module.
    """
    root = Path(ext_root)
    if not (root / "Configuration.xml").exists():
        return {"ok": False, "step": "precheck",
                "reason": f"не похоже на дамп расширения (нет Configuration.xml): {ext_root}"}
    try:
        conn = cli_connection_str(ib_connection)
    except ValueError as e:
        return {"ok": False, "step": "connection", "reason": str(e)}

    problems = validate_xml_files(root.rglob("*.xml"))
    if problems:
        return {"ok": False, "step": "xml_validate", "problems": problems}

    kill_report = None
    if kill_sessions:
        kill_report = kill_matching_processes(ib_connection)

    log_dir = Path(cfg["runtime_dir"]) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_load = log_dir / f"extfiles_{ext_name}_load.log"
    log_update = log_dir / f"extfiles_{ext_name}_update.log"

    cmd_load = (f'"{cfg["path_1c"]}" DESIGNER {conn} '
                f'/LoadConfigFromFiles "{root}" -Extension {ext_name} /Out "{log_load}"')
    rc, watch_err = _run(cmd_load, timeout, cfg, ib_connection, "LoadConfigFromFiles")
    if watch_err:
        return {**watch_err, "kill_report": kill_report}
    out_load = read_designer_log(log_load)
    if rc != 0:
        return {"ok": False, "step": "LoadConfigFromFiles", "returncode": rc,
                "log": out_load[-1500:], "kill_report": kill_report}

    cmd_update = f'"{cfg["path_1c"]}" DESIGNER {conn} /UpdateDBCfg -Extension {ext_name} /Out "{log_update}"'
    rc, watch_err = _run(cmd_update, timeout, cfg, ib_connection, "UpdateDBCfg")
    if watch_err:
        return {**watch_err, "kill_report": kill_report}
    out_update = read_designer_log(log_update)
    if rc != 0:
        return {"ok": False, "step": "UpdateDBCfg", "returncode": rc,
                "log": out_update[-1500:], "kill_report": kill_report}

    return {"ok": True, "load_log": out_load[-500:], "update_log": out_update[-500:],
            "kill_report": kill_report}


# BSL-снипет для просмотра ЛОГИНОВ информационной базы (платформенный уровень —
# ПользователиИнформационнойБазы, НЕ бизнес-справочник Пользователи) через run_module.
# Полезно, когда точный логин неизвестен (см. HANDOFF.md): без корректной
# аутентификации саму базу не запросить — это НЕ обход авторизации, а инструмент
# для владельца базы, который уже поднял раннер под ЛЮБЫМ валидным логином (например,
# успешно подключился DESIGNER-режимом) и хочет свериться со списком логинов ИБ.
LIST_IB_USERS_BSL = (
    "Процедура ВыполнитьЗадачу(ЛогВыполнения) Экспорт\n"
    "\tПользователи = ПользователиИнформационнойБазы.ПолучитьПользователи();\n"
    '\tЛогВыполнения = ЛогВыполнения + "Кол-во пользователей ИБ: " + Строка(Пользователи.Количество()) + Символы.ПС;\n'
    "\tДля Каждого П Из Пользователи Цикл\n"
    '\t\tЛогВыполнения = ЛогВыполнения + П.Имя + " | ПолноеИмя=" + П.ПолноеИмя'
    ' + " | ОСАутентификация=" + Строка(П.ОСАутентификация) + Символы.ПС;\n'
    "\tКонецЦикла;\n"
    '\tЛогВыполнения = ЛогВыполнения + "ГОТОВО";\n'
    "КонецПроцедуры\n"
)
