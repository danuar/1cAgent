#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#17: справочники по темам, которые дорого нащупывать заново каждый раз (в #7 на
это ушло ~15 минут вживую: перебор API YaXUnit, грабли СоздатьДокумент, формат
XML расширения). Отдаются ТОЛЬКО по явному вызову get_guide(topic) — не зашиты
в docstring обычных инструментов, чтобы не грузить контекст, когда не нужны.
"""

GUIDES = {
    "yaxunit_tests": """\
YaXUnit — как писать и гонять тесты (сжато, всё проверено вживую в #7).

1. Тест = ОБЩИЙ МОДУЛЬ (не заимствованный) внутри расширения YAXUNIT.
   Имя по конвенции: [Префикс_]Имя[_Суффикс]. Префиксы: Док_ (документ),
   Спр_ (справочник), РС_/РН_/РБ_ (регистры), ОМ_ (общий модуль). Суффиксы
   модуля: _МО (модуль объекта), _ММ (модуль менеджера), без суффикса —
   тестируем сам общий модуль/несколько методов объекта.

2. Обязательная экспортная процедура ИсполняемыеСценарии — регистрирует тесты,
   САМА логику/данные не готовит:
     Процедура ИсполняемыеСценарии() Экспорт
         ЮТТесты
             .ДобавитьТестовыйНабор("Имя набора")
                 .ДобавитьТест("ИмяМетода")              // рекомендуется читать как queue
                 .ДобавитьКлиентскийТест("ИмяМетода2")     // только клиент
                 .ДобавитьСерверныйТест("ИмяМетода3");     // только сервер
     КонецПроцедуры
   Движок сам сканирует общие модули расширения(й) на наличие этой процедуры —
   размещать в спецподсистеме НЕ нужно (та нужна только для кастомизации самого
   движка, см. доки customize-engine-behavior).

3. Тестовый метод — обычная Экспорт процедура, проверки через ЮТест:
     Процедура ИмяМетода() Экспорт
         Результат = <вызов проверяемого кода>;
         ЮТест.ОжидаетЧто(Результат).Равно(Ожидание);
         // ещё: .Заполнено() .ИмеетТип("Число, Строка") .Истина() .Ложь() и т.д.
     КонецПроцедуры

4. ГРАБЛИ (поймано вживую): ЮТест.Данные().СоздатьДокумент("Имя") возвращает
   ССЫЛКУ — её табличные части ТОЛЬКО НА ЧТЕНИЕ. Попытка
   .Товары.Добавить() -> рантайм-ошибка "Объект недоступен для изменения".
   Для документов с заполняемыми ТЧ использовать КонструкторОбъекта:
     Конструктор = ЮТест.Данные().КонструкторОбъекта("Документы.Имя")
         .ФикцияОбязательныхПолей()
         .ФикцияРеквизитов("Склад");                 // случайные валидные значения
     Конструктор.ТабличнаяЧасть("Товары").ДобавитьСтроку()
         .Фикция("Номенклатура")                      // авто-создаст элемент справочника
         .Установить("Цена", 100)
         .Установить("Количество", 2)
         .Установить("Сумма", 200);
     Ссылка = Конструктор.Записать();                 // или .Провести() если нужно проведение
   Для нескольких ТЧ — просто ещё раз Конструктор.ТабличнаяЧасть("Услуги")....
   Если ТЧ вообще не нужна для теста — просто не вызывать .Товары.Добавить()
   и передавать Ссылку/объект как есть.

5. Бизнес-логику, которую тестируем, ПРОЩЕ И БЕЗОПАСНЕЕ класть в СВОЙ общий
   модуль внутри того же расширения (например ОМ_РасчетДокументов), а не
   заимствовать/расширять модуль самого документа — тот путь (borrowed module)
   сложнее по формату файлов и не автоматизирован в deploy_module (см. ниже).

6. Деплой одним вызовом инструмента deploy_module (без ручного DumpConfigToFiles/
   правки XML/LoadConfigFromFiles — всё внутри):
     deploy_module(ib_connection, ext_name="YAXUNIT", module_name="ОМ_ИмяЛогики", bsl_code="...")
     deploy_module(ib_connection, ext_name="YAXUNIT", module_name="Док_ИмяТестов", bsl_code="...")
   Дальше сразу:
     run_tests(ib_connection, extensions=["YAXUNIT"], modules=["Док_ИмяТестов"])
   status: "ok" (всё зелёное) | "test_failed" (упал хотя бы один тест, разбирать
   cases[]) | "error" (движок не смог прогнать вообще — обычно "total": 0 значит
   тест-модуль не найден или не зарегистрировал ни одного теста).

7. Разовая предпосылка (сделана человеком руками при установке YaXUnit, не
   повторять): в Конфигураторе у расширения YAXUNIT сняты галки "Безопасный
   режим" и "Защита от опасных действий" — без этого тесты не смогут делать
   активные действия в базе (запись объектов и т.п.).
""",

    "main_config_overview": """\
Формат файлов ОСНОВНОЙ конфигурации (не расширения) — Документы/Справочники/
Регистры/ПланСчетов/Отчёты/Формы. Собрано вживую в задаче "билет №15"
(склад/накладные/СКД). ЭТО ИНДЕКС — сам по себе почти ничего не объясняет,
только указывает, за каким кусочком идти.

ПРАВИЛО ЭСКАЛАЦИИ (формализовано по ретроотчёту билета №15 — до этого
применялось интуитивно 3+ раза подряд и каждый раз спасало, но нигде не было
записано как процедура): если формат НОВОГО вида XML-узла/атрибута/события
угадан НЕВЕРНО уже 2 РАЗА ПОДРЯД (LoadConfigFromFiles/UpdateDBCfg упал, или —
хуже — прошёл без ошибки, но не сработал в реальном клиенте, см. #34) —
НЕ гадать в третий раз по памяти/аналогии. Вместо этого просить у пользователя
РЕАЛЬНЫЙ пример: пусть настроит нужное свойство/объект через настоящий
Конфигуратор (это надёжнее, чем воспроизводить GUI computer-use) и выгрузит
(dump_main_config/dump_extension) — сверяться с фактическим XML, а не
угадывать третий раз. Так нашлись Subsystem (#32), DCS <parameter> (#33) и
задним числом сам Event-баг форм (#34, см. пример прямо в этом дампе). Также
см. main_config_forms п. "ГРАБЛЯ" — конкретный пример класса риска "XML
синтаксически валиден, LoadConfigFromFiles/UpdateDBCfg прошли БЕЗ ОШИБКИ, но
семантически не то, что нужно платформе": успешная загрузка САМА ПО СЕБЕ не
подтверждает, что формат верный — только то, что XML не битый синтаксически.

Более узкие темы (берите ТОЛЬКО нужную, не весь main_config_* набор разом):

    main_config_internal_info — <InternalInfo>/<xr:GeneratedType>: какие
        категории нужны для какого вида метаданных + ChildObjects-теги
        регистрации в Configuration.xml. Нужен ВСЕГДА при добавлении
        любого нового объекта (кроме CommonModule/ScheduledJob/Role).
    main_config_types — формат <Type> для Строка/Число/Булево/Дата/Ссылка/
        Перечисление + минимальный блок <Properties> Attribute/Dimension/
        Resource + грабля с QuickChoice (Булево на объекте vs enum на
        атрибуте) + грабля с <xr:Field> в InputByString. Нужен при добавлении
        реквизитов/измерений/ресурсов.
    main_config_document — специфика Document: Posting/RegisterRecords/
        TabularSection/Forms-регистрация + ГЛАВНАЯ ГРАБЛЯ (ПередЗаписью vs
        ОбработкаПроведения для вычисляемых полей ТЧ). Нужен при написании
        документа с проведением.
    main_config_accounting — ChartOfAccounts (включая Ext/Predefined.xml для
        предопределённых счетов) + AccountingRegister.Correspondence. Нужен
        только если строите план счетов/регистр бухгалтерии.
    main_config_report_dcs — три уровня файлов отчёта с СКД + ГРАБЛЯ с
        экранированием "&" в тексте запроса (стоила ~10 минут зависшего
        процесса). Нужен только при добавлении отчёта.
    main_config_forms — формат Forms/Имя.xml + Ext/Form.xml. Нужен только
        если делаете форму руками (не полагаетесь на автогенерируемую).
    main_config_subsystem — формат Subsystems/Имя.xml (Content — список
        объектов для интерфейса/навигации). Нужен, чтобы созданные объекты
        вообще были видны пользователю в клиенте 1С (без подсистемы объекты
        существуют в метаданных, но не появляются ни в одном разделе интерфейса).
    main_config_setup — где лежит эталонная база-шпаргалка MetaTemplates,
        как её передампить + грабля с DESIGNER-подключением (/F vs File=).
        Нужен один раз в начале работы с основной конфигурацией.

См. также get_guide("extension_files") — тот же формат, но для расширений
(проще: CommonModule без InternalInfo).
""",

    "main_config_internal_info": """\
Объекты ОСНОВНОЙ конфигурации, порождающие ссылочные/наборные типы (Catalog,
Document, ChartOfAccounts, регистры, Enum, Report, DataProcessor, Constant),
ОБЯЗАТЕЛЬНО требуют блок <InternalInfo> с <xr:GeneratedType>. Без него
LoadConfigFromFiles падает: "Отсутствует внутренняя информация (узел
InternalInfo) для объекта X".

ВАЖНО: это НЕ фиксированные платформенные GUID (в отличие от InternalInfo
корневого Configuration.xml, где <xr:ContainedObject><xr:ClassId>/<xr:ObjectId>
— те завязаны на класс, не трогать). Для обычных объектов TypeId/ValueId —
случайные, генерируются заново под каждый объект (uuid4() подходит), важен
только СПИСОК КАТЕГОРИЙ (name строится как "<Категория-класс>.<ИмяОбъекта>",
category — короткое имя):

    Catalog/Document:
        Object, Ref, Selection, List, Manager   (5, в этом порядке)
    ChartOfAccounts:
        Object, Ref, Selection, List, Manager,
        ExtDimensionTypes, ExtDimensionTypesRow   (7 — ДАЖЕ при MaxExtDimensionCount=0
        два последних всё равно обязательны, проверено вживую)
    AccumulationRegister:
        Record, Manager, Selection, List, RecordSet, RecordKey   (6)
    InformationRegister:
        Record, Manager, Selection, List, RecordSet, RecordKey, RecordManager   (7)
    AccountingRegister:
        Record, ExtDimensions, RecordSet, RecordKey, Selection, List, Manager   (7)
    Enum:
        Ref, Manager, List   (3, без Object — Enum не редактируется руками)
    Report/DataProcessor:
        Object, Manager   (2, без Ref/Selection/List — не ссылочный тип)
    Constant:
        Manager, ValueManager, ValueKey   (3, по этим 3 категориям, не Object/Ref)
    TabularSection (внутри Document/Catalog/ChartOfAccounts):
        TabularSection, TabularSectionRow   (2; name = "<Класс>TabularSection[Row].
        <ИмяОбъекта>.<ИмяТЧ>", например "DocumentTabularSection.Doc.Строки")
    CommonModule / ScheduledJob / Role: InternalInfo НЕ нужен вообще (как и в
        расширениях).

Шаблон одного <xr:GeneratedType>:
    <xr:GeneratedType name="CatalogObject.Имя" category="Object">
        <xr:TypeId>{uuid4}</xr:TypeId>
        <xr:ValueId>{uuid4}</xr:ValueId>
    </xr:GeneratedType>
"name" склеивается из платформенного префикса класса (CatalogObject/CatalogRef/
CatalogSelection/CatalogList/CatalogManager, DocumentObject/DocumentRef/...,
AccumulationRegisterRecord/...Manager/...Selection/...List/...RecordSet/
...RecordKey, InformationRegisterRecord/...Manager/.../...RecordManager,
AccountingRegisterRecord/...ExtDimensions/...RecordSet/...RecordKey/.../.../
...Manager, EnumRef/EnumManager/EnumList, ReportObject/ReportManager,
DataProcessorObject/DataProcessorManager, ConstantManager/ConstantValueManager/
ConstantValueKey) + "." + Имя объекта.

ChildObjects корневого Configuration.xml — плоский список тегов-регистраций
(порядок не важен), имя тега = имя класса объекта:
    <Language>Русский</Language>
    <CommonModule>Имя</CommonModule>
    <Constant>Имя</Constant>
    <Catalog>Имя</Catalog>
    <Document>Имя</Document>
    <Enum>Имя</Enum>
    <Report>Имя</Report>
    <DataProcessor>Имя</DataProcessor>
    <InformationRegister>Имя</InformationRegister>
    <AccumulationRegister>Имя</AccumulationRegister>
    <ChartOfAccounts>Имя</ChartOfAccounts>
    <AccountingRegister>Имя</AccountingRegister>
    <ScheduledJob>Имя</ScheduledJob>
    <Role>Имя</Role>
""",

    "main_config_types": """\
ТИПЫ РЕКВИЗИТОВ/ИЗМЕРЕНИЙ/РЕСУРСОВ (тег <Type> внутри <Properties>
Attribute/Dimension/Resource) — подтверждено вживую:
    Строка (10, перем. длина):
        <v8:Type>xs:string</v8:Type>
        <v8:StringQualifiers><v8:Length>10</v8:Length>
            <v8:AllowedLength>Variable</v8:AllowedLength></v8:StringQualifiers>
    Число (15 цифр, 0 дробных, любой знак):
        <v8:Type>xs:decimal</v8:Type>
        <v8:NumberQualifiers><v8:Digits>15</v8:Digits><v8:FractionDigits>0</v8:FractionDigits>
            <v8:AllowedSign>Any</v8:AllowedSign></v8:NumberQualifiers>
    Булево:
        <v8:Type>xs:boolean</v8:Type>
    Дата (по аналогии с String/NumberQualifiers, НЕ проверено вживую —
    если упадёт, см. живой пример через describe_metadata/DumpConfigToFiles):
        <v8:Type>xs:dateTime</v8:Type>
        <v8:DateQualifiers><v8:DateFractions>Date</v8:DateFractions></v8:DateQualifiers>
    Ссылка на справочник:
        <v8:Type>cfg:CatalogRef.ИмяСправочника</v8:Type>   (префикс cfg:, не v8:!)
    Ссылка на перечисление:
        <v8:Type>cfg:EnumRef.ИмяПеречисления</v8:Type>
    Составной тип — несколько <v8:Type> подряд внутри одного <Type>.

Общий блок <Properties> для Attribute/Dimension/Resource (минимальный рабочий
набор, псевдо-шаблон — реальные примеры смотреть в MetaTemplates, см.
get_guide("main_config_setup")):
    <Attribute uuid="{uuid4}">
        <Properties>
            <Name>Имя</Name>
            <Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>Имя</v8:content></v8:item></Synonym>
            <Comment/>
            <Type>...</Type>
            <PasswordMode>false</PasswordMode>
            <Format/><EditFormat/><ToolTip/>
            <MarkNegatives>false</MarkNegatives><Mask/><MultiLine>false</MultiLine>
            <ExtendedEdit>false</ExtendedEdit>
            <MinValue xsi:nil="true"/><MaxValue xsi:nil="true"/>
            <FillChecking>DontCheck</FillChecking>
            <ChoiceFoldersAndItems>Items</ChoiceFoldersAndItems>
            <ChoiceParameterLinks/><ChoiceParameters/>
            <QuickChoice>Auto</QuickChoice>   <!-- ВНИМАНИЕ: на уровне АТРИБУТА это
                enum Auto/Use/DontUse; а на уровне САМОГО ОБЪЕКТА (Catalog/ChartOfAccounts)
                <QuickChoice> — БУЛЕВО (true/false)! Перепутать — типовая ошибка
                XDTO: "Отображение типа xsd:boolean в тип Булево". -->
            <CreateOnInput>Auto</CreateOnInput>
            <ChoiceForm/><LinkByType/><ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>
            <Indexing>DontIndex</Indexing><FullTextSearch>Use</FullTextSearch>
            <DataHistory>Use</DataHistory>
        </Properties>
    </Attribute>
Для Dimension регистров накопления/сведений добавляются свои поля (DenyIncompleteValues,
UseInTotals для накопления; Master/MainFilter/TypeReductionMode для сведений) — см. реальные
примеры. Для Resource регистра бухгалтерии — дополнительно <Balance>true</Balance>
(см. get_guide("main_config_accounting")).

ГРАБЛЯ: <InputByString> использует <xr:Field>, НЕ <Field> без префикса (легко
перепутать по аналогии с другими тегами без namespace) — платформа тоже даёт
XDTO-ошибку при неверном префиксе.
""",

    "main_config_document": """\
ДОКУМЕНТ — специфичные свойства (Properties корневого <Document>):
    <Posting>Allow</Posting>
    <RealTimePosting>Allow</RealTimePosting>
    <RegisterRecordsDeletion>AutoDeleteOnUnpost</RegisterRecordsDeletion>
    <RegisterRecordsWritingOnPost>WriteSelected</RegisterRecordsWritingOnPost>
    <SequenceFilling>AutoFill</SequenceFilling>
    <RegisterRecords>
        <xr:Item xsi:type="xr:MDObjectRef">AccountingRegister.Имя</xr:Item>
        <xr:Item xsi:type="xr:MDObjectRef">AccumulationRegister.Имя</xr:Item>
    </RegisterRecords>
    <PostInPrivilegedMode>true</PostInPrivilegedMode>
    <UnpostInPrivilegedMode>true</UnpostInPrivilegedMode>
Табличная часть — <TabularSection uuid="..."> со своим <InternalInfo> (см.
get_guide("main_config_internal_info"), категории TabularSection/
TabularSectionRow) внутри <ChildObjects> документа, а атрибуты ТЧ — вложенный
<ChildObjects><Attribute>...</Attribute></ChildObjects> внутри самой ТЧ (та же
структура Attribute, что и у реквизитов шапки — см. get_guide("main_config_types")).
Формы регистрируются И в ChildObjects документа (<Form>ИмяФормы</Form>), И как
отдельные файлы (см. get_guide("main_config_forms")). DefaultObjectForm
ссылается полным путём: Document.Имя.Form.ИмяФормы.

РЕГИСТР, на который документ ссылается через RegisterRecords, ДОЛЖЕН уже
существовать в конфигурации на момент LoadConfigFromFiles — иначе "Ни один из
документов не является регистратором для регистра" (проверено вживую:
регистр без хотя бы одного документа-регистратора вообще не загружается).
Создавайте регистр и документ ОДНИМ пакетом правок, либо регистр первым (но
без реального регистратора он тоже не пройдёт — так что либо одним пакетом,
либо документ БЕЗ Posting сначала, потом регистр, потом Posting документу).

ГЛАВНАЯ ГРАБЛЯ (поймано вживую, #билет15, стоила больше всего времени):
изменение значения колонки ТАБЛИЧНОЙ ЧАСТИ документа внутри его же
ОбработкаПроведения(Отказ, РежимПроведения) — НЕ СОХРАНЯЕТСЯ в саму запись
документа, хотя тут же корректно читается и используется для проводок/
движений В ЭТОМ ЖЕ прогоне (то есть в памяти присваивание отработало,
платформа явно уже произвела физическую запись шапки+ТЧ объекта ДО вызова
ОбработкаПроведения — движения пишутся отдельным, более поздним шагом). Не
спасают ни "Для Каждого Стр Из ТЧ Цикл: Стр.Поле=...", ни индексный
"ТЧ[Инд].Поле=...", ни повторное чтение через Товары[Инд] сразу после
присвоения в РАМКАХ проведения — persist не происходит НИ В ОДНОМ варианте
(проверено дважды, оба не сработали).

РАБОЧЕЕ РЕШЕНИЕ: считать и записывать вычисляемые поля ТЧ в
ПередЗаписью(Отказ) (выполняется РАНЬШЕ физической записи объекта — эти
изменения сохраняются штатно), а ОбработкаПроведения использовать только для
формирования Движения.* (регистры/проводки), читая уже посчитанные в
ПередЗаписью значения. Если для движений нужна ДРУГАЯ версия величины
(например средняя себестоимость БЕЗ распределённых допрасходов, в отличие от
итоговой Себестоимость строки С допрасходами для проводки) — просто
пересчитать её ещё раз тем же запросом внутри ОбработкаПроведения,
дублирование дешевле, чем полагаться на persist из ОбработкаПроведения.
""",

    "main_config_accounting": """\
ПЛАН СЧЕТОВ — предопределённые счета живут ОТДЕЛЬНЫМ файлом
<ИмяПланаСчетов>/Ext/Predefined.xml, НЕ в основном XML объекта:
    <?xml version="1.0" encoding="UTF-8"?>
    <PredefinedData xmlns="http://v8.1c.ru/8.3/xcf/predef" ... xsi:type="ChartOfAccountsPredefinedItems" version="2.19">
        <Item id="{uuid4}">
            <Name>Товары</Name>
            <Code>41</Code>
            <Description>Товары</Description>
            <AccountType>Active</AccountType>   <!-- Active | Passive | ActivePassive -->
            <OffBalance>false</OffBalance>
            <Order/>
            <AccountingFlags/>
            <ChildItems>...</ChildItems>   <!-- вложенные субсчета, опционально -->
        </Item>
    </PredefinedData>
Коды могут содержать точку ("90.01") без спецнастроек — CodeType для
ChartOfAccounts не задаётся отдельно (в отличие от Catalog), код всегда строка.

РЕГИСТР БУХГАЛТЕРИИ — Properties: <ChartOfAccounts>ChartOfAccounts.Имя</ChartOfAccounts>
обязателен, план счетов должен существовать. Ресурс с <Balance>true</Balance> —
обычная сумма проводки.

ГРАБЛЯ: <Correspondence> — по умолчанию НЕ ставьте false. Без корреспонденции
(false) движения используют одиночный <Счет>+<ВидДвижения> (как в регистре
накопления — Приход/Расход на один счёт за раз), а поля СчетДт/СчетКт в ОДНОЙ
строке движения (типичный парный BSL-код "Движение.СчетДт=...;
Движение.СчетКт=...;") доступны ТОЛЬКО при <Correspondence>true</Correspondence>.
Ошибка при несовпадении — "Поле объекта не обнаружено (СчетДт)".
""",

    "main_config_report_dcs": """\
ОТЧЁТ С СКД — три уровня файлов:
    Reports/Имя.xml                                    — дескриптор объекта (Object/
                                                          Manager InternalInfo, см.
                                                          get_guide("main_config_internal_info")),
                                                          MainDataCompositionSchema=
                                                          Report.Имя.Template.ИмяСхемы,
                                                          ChildObjects: <Template>ИмяСхемы</Template>
    Reports/Имя/Templates/ИмяСхемы.xml                 — дескриптор макета
                                                          (TemplateType=DataCompositionSchema)
    Reports/Имя/Templates/ИмяСхемы/Ext/Template.xml    — САМА схема СКД
                                                          (namespace DataCompositionSchema,
                                                          dataSource+dataSet(запрос)+
                                                          settingsVariant с группировками/
                                                          отбором/итогами) — это НЕ MDClasses-
                                                          формат, отдельная XSD (data-composition-
                                                          system/schema). Группировки/итоги/
                                                          промежуточные итоги настраиваются через
                                                          dcsset:item xsi:type="dcsset:StructureItemGroup"
                                                          с вложенными dcsset:groupItems (у самой
                                                          ВНУТРЕННЕЙ вложенной группы groupItems
                                                          может отсутствовать — тогда это просто
                                                          "детальные строки" без своей агрегации).

ПАРАМЕТРЫ ОТЧЁТА (например период) — подтверждено вживую, реальный пример от
пользователя (сам угадал НЕВЕРНО с первой попытки — тег называется НЕ
<parameters>, а <parameter>, ОДИН элемент НА параметр, сиблинг <dataSet>,
ДО <settingsVariant>):
    <parameter>
        <name>Период</name>
        <title xsi:type="v8:LocalStringType">
            <v8:item><v8:lang>ru</v8:lang><v8:content>Период</v8:content></v8:item>
        </title>
        <valueType><v8:Type>v8:StandardPeriod</v8:Type></valueType>
        <value xsi:type="v8:StandardPeriod">
            <v8:variant xsi:type="v8:StandardPeriodVariant">Custom</v8:variant>
            <v8:startDate>0001-01-01T00:00:00</v8:startDate>
            <v8:endDate>0001-01-01T00:00:00</v8:endDate>
        </value>
        <useRestriction>false</useRestriction>
    </parameter>
Стандартный период (тип v8:StandardPeriod) — рекомендуемый способ дать
пользователю выбор периода одним полем (даёт готовый пикер "Этот месяц/
квартал/..." в форме отчёта). В САМОМ ЗАПРОСЕ обращение к его границам —
через точку: &Период.ДатаНачала / &Период.ДатаОкончания (подтверждено).

ПРОИЗВОДНЫЕ ПАРАМЕТРЫ (expression) — рабочий паттерн для случая, когда запрос
исторически использует простые &ИмяПараметра (например &НачалоПериода/
&КонецПериода), а не хочется переписывать запрос на &Период.ДатаНачала:
завести ОТДЕЛЬНЫЕ параметры с <expression>, которые вычисляются из основного:
    <parameter>
        <name>НачалоПериода</name>
        <title xsi:type="v8:LocalStringType">
            <v8:item><v8:lang>ru</v8:lang><v8:content>Начало периода</v8:content></v8:item>
        </title>
        <valueType>
            <v8:Type>xs:dateTime</v8:Type>
            <v8:DateQualifiers><v8:DateFractions>DateTime</v8:DateFractions></v8:DateQualifiers>
        </valueType>
        <value xsi:type="xs:dateTime">0001-01-01T00:00:00</value>
        <useRestriction>true</useRestriction>
        <expression>&amp;Период.ДатаНачала</expression>
        <availableAsField>false</availableAsField>
    </parameter>
    <!-- аналогично КонецПериода с expression &amp;Период.ДатаОкончания -->
ГРАБЛЯ (поймано вживую на реальном примере пользователя — пары легко перепутать
местами): КонецПериода.expression должен ссылаться на &Период.ДатаОкончания,
НачалоПериода.expression — на &Период.ДатаНачала. Перепутанные местами дают
БЕЗ ОШИБКИ загружающийся отчёт, который молча возвращает 0 строк (диапазон
"дата МЕЖДУ концом И началом" пуст) — не падает нигде, только пустой результат,
проверять численно (тестовый прогон с широким диапазоном дат и известными
данными), а не полагаться на отсутствие ошибок при Load/Update.

"Включать в пользовательские настройки" ("быстрые параметры", доступ к
настройке без захода в "Ещё → Настроить") — ПОДТВЕРЖДЕНО вживую (реальный
пример от пользователя, добавлено через Конфигуратор). Блок
<dcsset:dataParameters> — сиблинг <dcsset:selection>, СРАЗУ ПОСЛЕ него,
ДО <dcsset:order>. ГРАБЛЯ: внутри — смесь ДВУХ namespace на соседних тегах,
не спутать: сам <item> и его "use"/"parameter"/"value" — namespace dcscor:,
а <userSettingID> — namespace dcsset: (именно так, не единообразно):
    <dcsset:dataParameters>
        <dcscor:item xsi:type="dcsset:SettingsParameterValue">
            <dcscor:use>false</dcscor:use>
            <dcscor:parameter>Период</dcscor:parameter>
            <dcscor:value xsi:type="v8:StandardPeriod">
                <v8:variant xsi:type="v8:StandardPeriodVariant">Custom</v8:variant>
                <v8:startDate>0001-01-01T00:00:00</v8:startDate>
                <v8:endDate>0001-01-01T00:00:00</v8:endDate>
            </dcscor:value>
            <dcsset:userSettingID>{uuid4}</dcsset:userSettingID>
        </dcscor:item>
    </dcsset:dataParameters>
Наличие непустого <dcsset:userSettingID> — то, что делает параметр "быстрым"
(показывается прямо на форме отчёта, не только в "Настроить..."). <dcscor:use>
— отдельный флаг (найден false в рабочем примере — не "включает быстрый
доступ", а скорее "принудительно использовать это ЗНАЧЕНИЕ по умолчанию").

ГРАБЛЯ (поймано вживую, стоило ~10 минут зависшего процесса): текст ЗАПРОСА
внутри тега <query> — это XML-СОДЕРЖИМОЕ, а параметры запроса 1С пишутся
через "&Имя" (ВЫБРАТЬ ... ГДЕ Дата МЕЖДУ &НачалоПериода И &КонецПериода) —
символ "&" в XML ОБЯЗАТЕЛЬНО экранировать как "&amp;НачалоПериода", иначе
LoadConfigFromFiles не падает быстро с понятной ошибкой, а ВИСНЕТ НАДОЛГО
(процесс DESIGNER молча работает минутами, /Out-лог остаётся пустым) —
выглядит как зависание, а не как ошибка формата.

Если LoadConfigFromFiles/UpdateDBCfg работает намного дольше типичных
секунд-десятков секунд для маленькой конфигурации (риск = скрытая
XML-ошибка, не обязательно реальная тяжесть операции) — НЕ ждать вслепую
много минут: ставить короткий subprocess timeout (30-60с достаточно для
объёма в один документ/регистр/отчёт), при истечении — убить процесс
(Stop-Process/taskkill по PID, это свой процесс, не пользовательская сессия)
и первым делом проверить XML-экранирование "&"/"<"/">" в ЛЮБОМ месте, где в
файл попадает 1С-СИНТАКСИС КАК ТЕКСТ (тексты запросов в DCS-схемах). Ещё
надёжнее — прогнать xml.etree.ElementTree.parse() по свежесозданному .xml
ПЕРЕД тем, как звать LoadConfigFromFiles: ловит это за миллисекунды
(src/core/xml_validate.py уже так делает во всех deploy-инструментах).
Обычные .bsl-файлы (Module.bsl/ObjectModule.bsl) НЕ являются XML — там "&Имя"
экранировать НЕ нужно, ловушка специфична именно для .xml-файлов.
""",

    "main_config_forms": """\
ФОРМЫ (Document/Catalog/Report) — три уровня файлов:
    .../Имя.xml               — дескриптор (FormType=Managed, UsePurposes)
    .../Имя/Ext/Form.xml      — САМА форма, namespace xcf/logform, НЕ MDClasses:
                                 <ChildItems> (InputField/Table/LabelField с DataPath
                                 вида "Объект.РеквизитШапки" или "Объект.ИмяТЧ.Колонка"),
                                 <Attributes> с главным <Attribute name="Объект">
                                 (Type=cfg:DocumentObject.Имя, MainAttribute=true).
    .../Имя/Ext/Form/Module.bsl — код формы (если нужен), тот же паттерн, что у
                                 CommonModule (utf-8-sig).
Регистрируется в ChildObjects родителя как <Form>Имя</Form> (плоский тег, без
вложенности), и отдельно в Properties родителя как Default*Form/Auxiliary*Form
(полный путь Вид.Имя.Form.ИмяФормы) — если формы нет, платформа генерирует
дефолтную автоматически (эти свойства можно оставлять пустыми <DefaultObjectForm/>,
и для большинства задач этого достаточно — ручную форму делайте только если
нужна нестандартная логика/раскладка).

ЭЛЕМЕНТЫ ФОРМЫ, ПОДТВЕРЖДЕНО ВЖИВУЮ (#билет15, загрузилось с ПЕРВОЙ попытки —
редкий случай, обычно в СКД/Subsystem угадывал через 2-3 итерации):

Группа полей в один ряд (например Номер+Дата рядом) — <UsualGroup>, сиблинг
других ChildItems, сама содержит ВЛОЖЕННЫЙ <ChildItems> с полями:
    <UsualGroup name="ИмяГруппы" id="N">
        <Group>Horizontal</Group>
        <ChildItems>
            <InputField name="Номер" id="N1">...</InputField>
            <InputField name="Дата" id="N2">...</InputField>
        </ChildItems>
    </UsualGroup>

ГРАБЛЯ (нашлась НЕ в этой сессии, а позже — живым тестом в клиенте): версия
ниже — <Event name="ИмяСобытия">.../Event> ПРЯМЫМ сиблингом полей InputField —
СИНТАКСИЧЕСКИ валидна и LoadConfigFromFiles/UpdateDBCfg проходят БЕЗ ОШИБКИ,
но обработчик в реальном клиенте НЕ СРАБАТЫВАЕТ. Ложноположительный сигнал —
именно тот класс риска "XML валиден, но семантически не то", см. ретроотчёт
по билету №15. НЕ ИСПОЛЬЗОВАТЬ:
    <InputField name="ТоварыКоличество" id="N">
        ...
        <Event name="ПриИзменении">ИмяПроцедуры</Event>   <!-- НЕ РАБОТАЕТ -->
    </InputField>

ПРАВИЛЬНЫЙ формат (подтверждён живым тестом: пользователь назначил обработчик
через реальный Конфигуратор — свойство поля "При изменении" — и выгрузил
итоговый XML). ДВА отличия от неверной версии: (1) тег события ВЛОЖЕН в
отдельный контейнер <Events>, а не сиблинг напрямую; (2) атрибут name — это
ВНУТРЕННИЙ (английский) идентификатор события платформы (OnChange), а НЕ
русское имя события из палитры свойств (ПриИзменении используется только как
часть ИМЕНИ ПРОЦЕДУРЫ по соглашению, не как значение name):
    <InputField name="ТоварыКоличество" id="18">
        <DataPath>Объект.Товары.Количество</DataPath>
        <EditMode>EnterOnInput</EditMode>
        <ExtendedEditMultipleValues>true</ExtendedEditMultipleValues>
        <ContextMenu name="ТоварыКоличествоКонтекстноеМеню" id="19"/>
        <ExtendedTooltip name="ТоварыКоличествоРасширеннаяПодсказка" id="20"/>
        <Events>
            <Event name="OnChange">ТоварыЦенаПриИзменении</Event>
        </Events>
    </InputField>
<Events> — сиблинг DataPath/EditMode/ContextMenu/ExtendedTooltip внутри самого
InputField; порядок остальных элементов внутри поля не критичен, но <Events>
должен быть контейнером, а не одиночным тегом <Event>. ПРАВИЛО: для ЛЮБОГО
нового вида обработчика события в форме (OnOpen, BeforeWrite и т.п.) сверяться
с реальным именем через живой пример из Конфигуратора, а не подставлять
русское имя события по аналогии — платформа хранит события ВСЕГДА под
английскими идентификаторами независимо от языка интерфейса.
Соответствующая клиентская процедура в Module.bsl — читает/пишет текущую
строку ТЧ через Элементы.ИмяТаблицы.ТекущиеДанные (без похода на сервер):
    &НаКлиенте
    Процедура ТоварыКоличествоПриИзменении(Элемент)
        ТекущиеДанные = Элементы.Товары.ТекущиеДанные;
        Если ТекущиеДанные <> Неопределено Тогда
            ТекущиеДанные.Сумма = ТекущиеДанные.Количество * ТекущиеДанные.Цена;
        КонецЕсли;
    КонецПроцедуры

Поле только для чтения — <ReadOnly>true</ReadOnly> внутри InputField (сиблинг
DataPath). Полезно для вычисляемых полей ТЧ (см. get_guide("main_config_document")
про ПередЗаписью) — показывает пользователю, что поле не редактируется руками.

Команда формы (кнопка на панели) — <Commands> на верхнем уровне формы (сиблинг
<ChildItems>/<Attributes>), автоматически появляется на <AutoCommandBar> без
дополнительной привязки кнопки (не проверялось, требует ли РУЧНОЙ CommandBarButton
в НЕ-auto командной панели):
    <Commands>
        <Command name="ПоказатьДвижения" id="N">
            <Title><v8:item><v8:lang>ru</v8:lang><v8:content>Показать движения</v8:content></v8:item></Title>
            <Action>ПоказатьДвижения</Action>
        </Command>
    </Commands>
Обработчик — клиентская процедура с ИМЕНЕМ, совпадающим с <Action>, первый
параметр — Command:
    &НаКлиенте
    Процедура ПоказатьДвижения(Command)
        ...
    КонецПроцедуры

Просмотр движений документа (регистр накопления + регистр бухгалтерии) БЕЗ
БСП (нет стандартной команды "Движения документа" на голой платформе) — своя
команда + серверная функция с двумя запросами (РегистрНакопления.Имя ГДЕ
Регистратор=&Ссылка; РегистрБухгалтерии.Имя ГДЕ Регистратор=&Ссылка,
СчетДт.Код/СчетКт.Код для регистра с Correspondence=true), результат — просто
текст через ПоказатьПредупреждение(, Текст) на клиенте (сервер строку
собирает, клиент показывает) — простой и надёжный вариант без доп. таблиц/
атрибутов формы.
""",

    "main_config_subsystem": """\
ПОДСИСТЕМА — единственный способ сделать созданные объекты ВИДИМЫМИ в
интерфейсе клиента 1С (без неё объекты существуют в метаданных и доступны
программно, но не появляются ни в одном разделе/панели навигации). Формат
подтверждён вживую (#билет15, взят с реального примера — дважды угадал
неверно порядок элементов до этого, не гадать заново).

Subsystems/Имя.xml — ЕДИНСТВЕННЫЙ файл (без Ext-подпапки), InternalInfo НЕ
нужен (как у Role/CommonModule/ScheduledJob). КРИТИЧНО: <Content> лежит
ВНУТРИ <Properties>, ПОСЛЕДНИМ элементом (не рядом с ChildObjects, не перед
ChildObjects — обе эти раскладки дают ошибку формата документа "читаемое
свойство не соответствует ожидаемому", которая уходит ТОЛЬКО во всплывающий
диалог Конфигуратора, а НЕ в /Out-лог LoadConfigFromFiles — то есть если
LoadConfigFromFiles падает с returncode≠0 и ПУСТЫМ логом на подсистеме,
причина почти наверняка именно в порядке элементов, а не в зависании):

    <Subsystem uuid="{uuid4}">
        <Properties>
            <Name>ИмяПодсистемы</Name>
            <Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>...</v8:content></v8:item></Synonym>
            <Comment/>
            <IncludeHelpInContents>false</IncludeHelpInContents>
            <IncludeInCommandInterface>true</IncludeInCommandInterface>
            <UseOneCommand>false</UseOneCommand>
            <Explanation/>
            <Picture/>
            <Content>
                <xr:Item xsi:type="xr:MDObjectRef">Catalog.Имя</xr:Item>
                <xr:Item xsi:type="xr:MDObjectRef">Document.Имя</xr:Item>
                <xr:Item xsi:type="xr:MDObjectRef">Report.Имя</xr:Item>
                <!-- любые объекты основной конфигурации, полное имя Вид.Имя -->
            </Content>
        </Properties>
        <ChildObjects/>   <!-- вложенные ПОДСИСТЕМЫ (иерархия разделов), не содержимое -->
    </Subsystem>

Регистрация — обычный плоский тег в ChildObjects корневого Configuration.xml:
    <Subsystem>ИмяПодсистемы</Subsystem>
Порядок среди других тегов ChildObjects не важен (в отличие от порядка
ВНУТРИ самого файла подсистемы, который важен).
""",

    "main_config_setup": """\
ЭТАЛОННАЯ БАЗА-ШПАРГАЛКА: постоянный проектный актив (НЕ разовая задача) —
файловая ИБ work\\MetaTemplates с вручную созданными минимальными объектами
каждого вида (Catalog/Document+2 формы/TabularSection/AccumulationRegister/
InformationRegister/ChartOfAccounts/AccountingRegister/Enum/Constant/Report+СКД/
DataProcessor/ScheduledJob/CommonModule/Role) — источник ВСЕХ примеров в
остальных main_config_* темах. Если нужен ещё формат (например реальный
xs:dateTime, или Перечисление со значением-ссылкой в другом объекте) — не
гадать, а дампнуть эту базу заново:
    python -c "import subprocess; subprocess.run(
        r'\\"<path_1c>\\" DESIGNER /F \\"<work>\\\\MetaTemplates\\" '
        r'/DumpConfigToFiles \\"<runtime>\\\\config_src\\\\MetaTemplates\\" '
        r'/DisableStartupMessages /Out \\"<runtime>\\\\logs\\\\metatemplates_dump.log\\"',
        shell=True, timeout=120)"
(read-only, ничего не портит; при необходимости расширить набор объектов —
попросить пользователя добавить нужный вид через Конфигуратор руками, это
быстрее и надёжнее компьютерного управления GUI).

ГРАБЛЯ ПОДКЛЮЧЕНИЯ (чуть не стоила часа отладки): подключение DESIGNER/
ENTERPRISE к УЖЕ СУЩЕСТВУЮЩЕЙ базе — ФЛАГ /F "путь" (файловая) или /S
"сервер\\база" (серверная), а НЕ строка File="путь";/Srvr=...;Ref=...; напрямую
как аргумент — та декларативная форма (Key="value";...) годится ТОЛЬКО для
CREATEINFOBASE (создание НОВОЙ базы: `CREATEINFOBASE File="путь"`). Если
передать File="..." как позиционный аргумент DESIGNER/ENTERPRISE — платформа
молча НЕ подключается к базе, а открывает лаунчер со списком ИБ (пустой лог,
пустой результат dump, никакой ошибки в returncode). Используйте
src.core.ib_connection.cli_connection_str(ib_connection) — уже делает это
правильно, не собирайте команду руками мимо неё. Также вызывать через
subprocess.run(cmd, shell=True) (как во всём проекте), а НЕ через PowerShell
"& 'путь' арг1 арг2" — ненадёжно передаёт код возврата и может открыть GUI-лаунчер
вместо тихого фонового вызова.
""",

    "extension_files": """\
Формат файлов расширения 1С для ручной правки без EDT (нужен, если
deploy_module не покрывает случай — например, заимствование/расширение
модуля УЖЕ СУЩЕСТВУЮЩЕГО объекта основной конфигурации, а не новый общий
модуль внутри расширения).

ПРАВИЛО ЭСКАЛАЦИИ (то же самое, что в get_guide("main_config_overview")):
формат нового узла угадан неверно 2 раза подряд — не гадать третий раз,
просить у пользователя реальный пример через Конфигуратор + дамп.

Структура (DumpConfigToFiles -Extension <Имя>):
    Configuration.xml                        — корень, <ChildObjects> — плоский
                                                список ИМЁН всех объектов расширения
                                                (без учёта типа-вложенности)
    CommonModules/<Модуль>.xml                — дескриптор объекта (uuid, свойства)
    CommonModules/<Модуль>/Ext/Module.bsl     — сам код, UTF-8 С BOM (encoding="utf-8-sig")

Новый (не заимствованный) общий модуль — минимум для добавления:
    1. Сгенерировать uuid, записать CommonModules/<Имя>.xml по шаблону
       (см. module_deploy.py:_MODULE_XML_TEMPLATE).
    2. CommonModules/<Имя>/Ext/Module.bsl — сам код.
    3. Дописать <CommonModule>Имя</CommonModule> в <ChildObjects> Configuration.xml
       (порядок не важен, главное — до закрывающего </ChildObjects>).
    Это и делает deploy_module() автоматически.

Заимствование/расширение объекта ОСНОВНОЙ конфигурации (например, добавить
метод в модуль менеджера существующего документа) — СЛОЖНЕЕ, deploy_module
пока НЕ умеет: требует ObjectBelonging=Adopted, маппинг InternalInfo на
UUID объекта в основной конфигурации, и работы с частичным диффом модуля
(не весь модуль, а только добавленные методы). Не пытаться руками собирать
это по аналогии с обычным CommonModule — нужно исследовать формат отдельно
(взять существующий пример заимствованного объекта через DumpConfigToFiles
у любого готового расширения, которое такое делает).

Применение изменений (ВСЕГДА раздельными вызовами subprocess, НЕ чейнить
через ";" в одной команде PowerShell — однажды воспроизведено вживую, что
чейн закатывает старое содержимое модуля без ошибки в логе):
    1cv8.exe DESIGNER <conn> /LoadConfigFromFiles "<dir>" -Extension <Имя> /Out <log>
    1cv8.exe DESIGNER <conn> /UpdateDBCfg -Extension <Имя> /Out <log>
Пустой /Out-лог НЕ значит успех сам по себе — проверяйте returncode, при
сомнении перепроверьте повторным DumpConfigToFiles.
""",
}


def get_guide_text(topic: str = "") -> str:
    if not topic:
        return "Доступные темы: " + ", ".join(GUIDES.keys())
    if topic not in GUIDES:
        return f"Нет темы {topic!r}. Доступные: " + ", ".join(GUIDES.keys())
    return GUIDES[topic]
