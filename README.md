# DirectP2P LAB 0.2 — отдельная диагностическая ветка

**Изолированный эксперимент Android ↔ Android и Android ↔ Python с прямым UDP (без игрового relay).** Это не ветка производственного `U-like/p2p_messenger`.

## Где исходники

Полный проект DirectP2P LAB **0.2** находится в [`directp2p-project.tar.xz`](directp2p-project.tar.xz), унаследованном от коммита [`9d8e93c`](https://github.com/U-like/weaps/commit/9d8e93c05cb83cdc471ef625fc6d49c8a7e2915e) «Add DirectP2P 0.2 cross-network STUN, manual punching and diagnostic». Этот коммит успешно собран [GitHub Actions](https://github.com/U-like/weaps/actions/runs/40917637753).

```bash
tar -xJf directp2p-project.tar.xz
cd directp2p-lab
python3 -m unittest discover -s tests -v
python3 python/diagnose_ui.py
```

Папка `directp2p-lab/android/` содержит Kotlin/Gradle Android-приложение. Отдельные APK доступны в успешном CI artifact. В архиве находится версия 0.2 с STUN, ручными OFFER/ANSWER, UDP hole punching и JSON-диагностикой. Результаты физических тестов записаны в [NAT_TEST_MATRIX.md](NAT_TEST_MATRIX.md).

## Состояние исследования

- Два телефона в мобильных сетях разных операторов: **DIRECT подтверждён**.
- Домашний Wi-Fi ↔ мобильный оператор B: **DIRECT подтверждён**.
- Домашний Wi-Fi ↔ мобильный оператор A: **DIRECT не установлен**.
- Стабильность внешнего UDP mapping заметно различается, однако точную причину сбоя пока не доказали.
- В следующей диагностической версии нужны синхронный старт, сырые UDP счётчики, mapping/filtering и IPv6.

**Ничего не изменено в `U-like/p2p_messenger`.** Эта ветка сохраняет лабораторные результаты и изолированную кодовую базу отдельно.

*Конфиденциальность:* публичный репозиторий, поэтому полные IP-адреса пользователей и JSON-сессии сюда не добавлены.
