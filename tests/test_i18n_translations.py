from bot.i18n.translations import t


def test_beta_critical_bot_texts_have_primary_language_variants():
    keys = [
        "access_wrong_chat",
        "invite_wrong_chat_original",
        "shared_start_neutral",
        "person_role_prompt",
        "worker_no_rights_invite",
        "site_created_qr_ready",
    ]

    for key in keys:
        for locale in ["de", "uk", "ru", "en"]:
            assert t(key, locale) != key


def test_site_created_translation_keeps_site_name_placeholder():
    assert "Consum-Quartier" in t("site_created_qr_ready", "en").format(site_name="Consum-Quartier")
