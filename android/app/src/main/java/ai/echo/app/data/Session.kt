package ai.echo.app.data

import android.content.Context
import android.content.SharedPreferences
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/** Tokens are AES-GCM encrypted with a non-exportable Android Keystore key. */
private object Vault {
    private const val ALIAS = "echo_session_key"

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(
                KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build(),
            )
        }.generateKey()
    }

    fun encrypt(plain: String): String {
        val c = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val out = c.iv + c.doFinal(plain.toByteArray())
        return Base64.encodeToString(out, Base64.NO_WRAP)
    }

    fun decrypt(enc: String): String? = runCatching {
        val raw = Base64.decode(enc, Base64.NO_WRAP)
        val c = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, raw, 0, 12)) }
        String(c.doFinal(raw, 12, raw.size - 12))
    }.getOrNull()
}

class Session(context: Context) {
    private val prefs: SharedPreferences = context.getSharedPreferences("echo_session", Context.MODE_PRIVATE)

    private fun secret(k: String): String? = prefs.getString(k, null)?.let(Vault::decrypt)

    private val _signedIn = MutableStateFlow(prefs.getString(K_REFRESH, null) != null)
    val signedIn: StateFlow<Boolean> = _signedIn

    val accessToken: String? get() = secret(K_ACCESS)
    val refreshToken: String? get() = secret(K_REFRESH)
    val expiresAt: Long get() = prefs.getLong(K_EXPIRES, 0)
    val userId: String? get() = prefs.getString(K_USER, null)
    val email: String? get() = prefs.getString(K_EMAIL, null)
    val name: String? get() = prefs.getString(K_NAME, null)

    @Synchronized
    fun save(s: AuthSession) {
        val exp = s.expires_at ?: (System.currentTimeMillis() / 1000 + (s.expires_in ?: 3600))
        prefs.edit()
            .putString(K_ACCESS, Vault.encrypt(s.access_token)).putString(K_REFRESH, Vault.encrypt(s.refresh_token)).putLong(K_EXPIRES, exp)
            .putString(K_USER, s.user.id).putString(K_EMAIL, s.user.email).putString(K_NAME, s.user.name ?: prefs.getString(K_NAME, null))
            .apply()
        _signedIn.value = true
    }

    @Synchronized
    fun clear() {
        prefs.edit().clear().apply()
        _signedIn.value = false
    }

    companion object {
        private const val K_ACCESS = "access"
        private const val K_REFRESH = "refresh"
        private const val K_EXPIRES = "expires_at"
        private const val K_USER = "user_id"
        private const val K_EMAIL = "email"
        private const val K_NAME = "name"
    }
}
