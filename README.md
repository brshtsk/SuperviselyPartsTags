# Supervisely app: car parts side tagging

![logo-ml.png](https://raw.githubusercontent.com/brshtsk/SuperviselyPartsTags/main/img/logo-ml.png)

Приложение автоматически проставляет object-level теги стороны (`side`) для парных деталей,
используя image-level тег ракурса автомобиля (`view`) и детерминированные правила.

## Что делает

- читает существующие polygon-объекты на изображении;
- для поддерживаемых парных классов назначает:
  - `side = left|right` (когда правило уверенно),
  - `side_source = auto`,
  - `needs_review = yes|no`,
  - `side_reason = ...`;
- соблюдает политику перезаписи (`overwrite_existing_side_tags`);
- поддерживает `dry_run` (без загрузки аннотации обратно в Supervisely).

## Поддерживаемые парные классы

- Headlight
- Tail-light
- Mirror
- Front-window
- Back-window
- Front-door
- Back-door
- Front-wheel
- Back-wheel
- Fender
- Quarter-panel
- Rocker-panel

## Непарные/центральные классы (сторона не назначается)

- Roof
- Hood
- Trunk
- Grille
- License-plate
- Windshield
- Back-windshield
- Front-bumper
- Back-bumper

## Запуск

1. Укажите `Image ID` (или `Dataset ID`).
2. Включите `use_existing_view_tag`, чтобы использовать уже проставленный image tag `view`.
3. Нажмите **Assign side tags**.

Если `dry_run=true`, приложение только покажет логику и summary, но не загрузит новую annotation.

