import os
import pytest
from app.smtp_service import encrypt_password, decrypt_password, validate_smtp_config
from app.alert_state import _is_alert_already_sent, _record_sent_alert, _load_local_sent_alerts, _save_local_sent_alerts

def test_encryption_decryption():
    # Test encryption and decryption with default key fallback
    pwd = "my_super_secure_smtp_password"
    enc = encrypt_password(pwd)
    assert enc != pwd
    dec = decrypt_password(enc)
    assert dec == pwd

def test_mutual_exclusion_tls_ssl():
    # STARTTLS and SSL must not be both True
    with pytest.raises(ValueError, match="STARTTLS.*e SSL não podem estar ativos"):
        validate_smtp_config(use_tls=True, use_ssl=True)
    
    # Valid configurations should not raise error
    validate_smtp_config(use_tls=True, use_ssl=False)
    validate_smtp_config(use_tls=False, use_ssl=True)
    validate_smtp_config(use_tls=False, use_ssl=False)

def test_antispam_and_local_rotation(tmp_path, monkeypatch):
    # Mock fallback file
    mock_file = tmp_path / "sent_alerts.json"
    monkeypatch.setattr("app.alert_state.SENT_ALERTS_FILE", mock_file)
    # Ensure supabase is mocked as None
    monkeypatch.setattr("app.alert_state._supabase", lambda: None)
    
    fingerprint = "abc123sha256"
    tipo = "expiring"
    dest = "test@example.com"
    val = "2026-07-20T00:00:00Z"
    
    # Not sent yet
    assert not _is_alert_already_sent(fingerprint, tipo, dest, val)
    
    # Record sending
    _record_sent_alert(fingerprint, tipo, dest, val)
    
    # Must be recognized as sent
    assert _is_alert_already_sent(fingerprint, tipo, dest, val)
    
    # Check rotation to 1000 items
    alerts = []
    for i in range(1050):
        alerts.append({
            "fingerprint_sha256": f"fp_{i}",
            "tipo_alerta": "expired",
            "destinatario": "rot@example.com",
            "data_validade": val,
            "sent_at": "2026-06-20T00:00:00Z"
        })
    _save_local_sent_alerts(alerts)
    loaded = _load_local_sent_alerts()
    assert len(loaded) == 1000
    # The first 50 should be discarded, meaning fp_0 is gone, fp_50 is the first element
    assert loaded[0]["fingerprint_sha256"] == "fp_50"
