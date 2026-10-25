"""UI strings for the settings app.

Add a language: copy the "en" block, translate the values, add the code + native name to LANGS.
Missing keys fall back to English.
"""
import ctypes

LANGS = {"en": "English", "ru": "Русский"}

STRINGS = {
    "en": {
        "title": "Arctis OLED — visualizer",
        "style.auto": "Auto: switch on each track",
        "style.bars": "Bars", "style.blocks": "LED blocks", "style.mirror": "Mirror",
        "style.mountain": "Mountain", "style.wave": "Oscilloscope", "style.waterfall": "Waterfall",
        "style.radial": "Radial", "style.scope": "Stereo scope", "style.rings": "Kick rings",
        "idle.battery": "Battery levels", "idle.clock": "Big clock", "idle.blank": "Blank screen",
        "pv.idle": "Show idle screen",
        "pv.live": "Source: Arctis audio (live)",
        "pv.demo": "Source: demo signal (nothing playing)",
        "svc.title": "Base display service",
        "svc.on": "● running", "svc.off": "○ stopped", "svc.start": "Start", "svc.stop": "Stop",
        "grp.style": "Visualization",
        "grp.auto": "Auto mode: styles in rotation",
        "auto.every": "and every", "auto.min_hint": "min (0 = on track change only)",
        "grp.look": "Look",
        "look.sens": "Sensitivity", "look.db": "{db} dB", "look.punchy": "punchier", "look.flat": "smoother",
        "look.strip": "Bottom strip with text and VU",
        "look.battery": "Battery in header", "look.clock": "Clock in header",
        "look.strip_hint": "Strip text: A–Z, 0–9, up to 10 characters",
        "look.bright": "Brightness", "look.bright_val": "{v} of 10",
        "look.care": "OLED care mode",
        "look.care_hint": "pixel shift every minute, idle screen 3× dimmer",
        "grp.idle": "When it's quiet",
        "idle.after": "After 20 s show", "idle.off": "Turn screen off after", "min": "min",
        "btn.apply": "Apply to base", "btn.revert": "Revert",
        "btn.settings": "Settings", "btn.support": "Support the project",
        "st.dirty": "unsaved changes", "st.saved": "saved", "st.applied": "applied, base updates in ~2 s",
        "dlg.title": "Settings", "dlg.lang": "Language", "dlg.lang_auto": "System default",
        "dlg.tray": "Minimize and close to the tray",
        "dlg.app_start": "Start this app in the tray when Windows starts",
        "dlg.svc_start": "Start the base display when Windows starts",
        "dlg.about": "Version {v} · GPL-3.0", "dlg.github": "Project on GitHub",
        "dlg.ok": "OK", "dlg.cancel": "Cancel",
        "tray.open": "Open settings", "tray.style": "Visualization",
        "tray.svc_start": "Start base display", "tray.svc_stop": "Stop base display",
        "tray.exit": "Exit", "tray.hint": "Arctis OLED keeps running in the tray",
    },
    "ru": {
        "title": "Arctis OLED — визуализация",
        "style.auto": "Авто: смена по трекам",
        "style.bars": "Столбики", "style.blocks": "LED-сегменты", "style.mirror": "Зеркало",
        "style.mountain": "Горы", "style.wave": "Осциллограф", "style.waterfall": "Водопад",
        "style.radial": "Лучи", "style.scope": "Стерео-гониометр", "style.rings": "Кольца от бочки",
        "idle.battery": "Заряд батарей", "idle.clock": "Большие часы", "idle.blank": "Пустой экран",
        "pv.idle": "Показать экран простоя",
        "pv.live": "Источник: звук с Arctis (живой)",
        "pv.demo": "Источник: демо-сигнал (музыка не играет)",
        "svc.title": "Служба на базе",
        "svc.on": "● работает", "svc.off": "○ остановлена", "svc.start": "Запустить", "svc.stop": "Остановить",
        "grp.style": "Визуализация",
        "grp.auto": "Авто-режим: что крутить",
        "auto.every": "и ещё каждые", "auto.min_hint": "мин (0 = только по трекам)",
        "grp.look": "Вид",
        "look.sens": "Чувствительность", "look.db": "{db} дБ", "look.punchy": "ярче", "look.flat": "ровнее",
        "look.strip": "Нижняя полоса с ником и VU",
        "look.battery": "Батарея в шапке", "look.clock": "Часы в шапке",
        "look.strip_hint": "Ник: латиница, цифры, до 10 знаков",
        "look.bright": "Яркость", "look.bright_val": "{v} из 10",
        "look.care": "Бережный режим OLED",
        "look.care_hint": "сдвиг картинки раз в минуту, экран простоя в 3 раза тусклее",
        "grp.idle": "Когда тихо",
        "idle.after": "Через 20 с показать", "idle.off": "Гасить экран через", "min": "мин",
        "btn.apply": "Применить на базу", "btn.revert": "Отменить",
        "btn.settings": "Настройки", "btn.support": "Поддержать проект",
        "st.dirty": "есть изменения", "st.saved": "сохранено", "st.applied": "применено, база обновится за ~2 с",
        "dlg.title": "Настройки", "dlg.lang": "Язык", "dlg.lang_auto": "Как в системе",
        "dlg.tray": "Сворачивать и закрывать в трей",
        "dlg.app_start": "Запускать приложение в трее вместе с Windows",
        "dlg.svc_start": "Запускать экран базы вместе с Windows",
        "dlg.about": "Версия {v} · GPL-3.0", "dlg.github": "Проект на GitHub",
        "dlg.ok": "OK", "dlg.cancel": "Отмена",
        "tray.open": "Открыть настройки", "tray.style": "Визуализация",
        "tray.svc_start": "Запустить экран базы", "tray.svc_stop": "Остановить экран базы",
        "tray.exit": "Выход", "tray.hint": "Arctis OLED работает в трее",
    },
}

_cur = "en"


def system_lang():
    """Windows UI language -> one of LANGS (primary language id 0x19 = Russian)."""
    try:
        lid = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
    except Exception:
        return "en"
    return {0x19: "ru"}.get(lid, "en")


def set_lang(code):
    global _cur
    _cur = code if code in STRINGS else system_lang()
    return _cur


def t(key, **kw):
    text = STRINGS[_cur].get(key) or STRINGS["en"].get(key, key)
    return text.format(**kw) if kw else text
