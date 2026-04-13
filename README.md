# Supervisely app: car parts side tagging

[![Project](https://img.shields.io/badge/Project-AutoInspect-black?logo=github)](https://github.com/DedovInside/AutoInspect/tree/ml/ml)

![logo-ml.png](https://raw.githubusercontent.com/brshtsk/SuperviselyPartsTags/main/img/logo-ml.png)

Приложение автоматически проставляет object-level теги стороны (`side`) для парных деталей,
используя только существующий image-level тег ракурса автомобиля (`view`/`car_view`) и детерминированные правила.

## Что делает

- читает существующие polygon-объекты на изображении;
- для поддерживаемых парных классов назначает:
  - `side = left|right` (когда правило уверенно),
  - `side_source = auto`,
  - `needs_review = yes|no`,
  - `side_reason = ...`;
- не перезаписывает уже существующий object-tag `side`;
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
2. При необходимости настройте `pair_size_ratio_threshold`.
3. Нажмите **Assign side tags**.

Если `dry_run=true`, приложение только покажет логику и summary, но не загрузит новую annotation.

### Что такое `pair_size_ratio_threshold`

Порог используется, когда для одного класса найдено ровно 2 объекта в косом ракурсе
(`front-left`, `front-right`, `back-left`, `back-right`).

- считается отношение площадей `больший / меньший`;
- если отношение меньше порога, оба объекта помечаются как `needs_review=yes`;
- если отношение больше или равно порогу, больший объект считается на доминирующей стороне ракурса,
  меньший - на противоположной.

