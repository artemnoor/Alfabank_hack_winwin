# Модель-слепой аудит разметки T08, 2026-10-14

## Метод

Два независимо записанных offline-прохода проверяли synthetic corpus labels и критерии taxonomy, не используя предсказания Jev для выбора или изменения gold. Это аудит ясности правил и согласованности разметки, а не оценка качества модели. В ходе последующей технической сверки один из ревьюеров подтвердил свою позицию по e33 и уточнил, что часть прежнего списка была классифицирована как event-label disputes, а не topic ties.

Taxonomy 0.3.0-spike, baseline corpus и gold labels сохранены без изменений. Все решения остаются открытыми для human adjudication и требуют цитирования evidence spans в новой версии датасета.

## Разногласия и вопросы adjudication

### e33-multi-price-shortage — event-label dispute

Ревьюер A считает, что в тексте прямо установлено изменение цены, но не установлено операционное ограничение запасов/мощностей; предлагает для обсуждения только `price_cost_change`.

Ревьюер B считает, что описанный дефицит прямо поддерживает `shortage_capacity_constraint` вместе с `price_cost_change`, но видит возможный спор по основной теме: `industry_trade_supply` против `economy_finance`.

**Решение:** gold post hoc не менять. Независимому человеку следует выбрать трактовку по исходному синтетическому тексту, сослаться на конкретную фразу-доказательство и записать результат только в новую adjudicated dataset version.

### e34-multi-insolvency-legal — event-label boundary

Отдельно решить, достаточно ли описанного последующего обращения кредитора для `legal_enforcement`, помимо `insolvency_default`, или это лишь обычная процедура банкротства. Правило должно различать самостоятельное действие кредитора и юридический механизм основного события.

### e35-multi-labor-investment — event-label boundary

Инвестиция подтверждена. `labor_workforce_event` зависит от того, считать ли объявленный будущий найм 400 человек существенным изменением штата; в taxonomy не определена граница между таким обязательством и обычным планом найма.

### Topic boundaries

Для adjudication темы отдельно отмечены e10, e14, e18, e28, e30 и e45. Пары e09/e10 и e13/e14 полезны как контрастные примеры; в подтверждённом ревью-проходе неоднозначными были e10 и e14. e28 дополнительно имеет event-boundary вопрос: мера по лимиту водозабора может подпадать под `regulation_tax_change`, если текст подтверждает формальное правило.

## Предложения для будущей taxonomy revision

1. Уточнить правило главной темы и провести adjudication похожих trade и tax/regulatory stories.
2. Для event labels указывать фразу, удовлетворяющую positive criterion; не выводить shortage только из роста цены.
3. Описать lifecycle: rumor, discussion, proposal, formal announcement, adoption/effective date, completed action и confirmed outcome.
4. Согласовать смысл `uncertain` для out-of-list event отдельно от недостатка evidence. В baseline e47 имеет out-of-list business event без insufficient-evidence signal, но expected status `uncertain`; e50 отражает недостаток содержания.
5. Если нужны новые labels, отдельно оценить fraud/corruption, крупные contract/order wins/losses и partnerships/JVs. Это proposal, не автоматическое расширение v0.3.
6. Провести двойную независимую разметку, затем adjudication, до использования метрик как evidence.

## Ограничения

Deep corpus содержит 160 synthetic cases, но labels остаются draft от одного автора; split D доступен в репозитории и не является blind holdout. Ревьюеры не проводили аудит реальных новостей и не оценивали Jev. Этот документ не содержит модельных предсказаний или метрик. Ни одно расхождение не было разрешено с использованием model output.
