package ai.echo.app.capture

import android.content.Context
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.Build

/** Chooses phone mic vs Bluetooth earbud mic according to the user's earbud policy. */
class AudioRouter(context: Context, private val policy: () -> String) {
    private val am = context.getSystemService(AudioManager::class.java)
    var current: String = "phone"
        private set
    private var scoActive = false

    fun inCall(): Boolean = am.mode == AudioManager.MODE_IN_CALL || am.mode == AudioManager.MODE_IN_COMMUNICATION && !scoActive

    private fun btInput(): AudioDeviceInfo? = am.getDevices(AudioManager.GET_DEVICES_INPUTS).firstOrNull {
        it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO || (Build.VERSION.SDK_INT >= 31 && it.type == AudioDeviceInfo.TYPE_BLE_HEADSET)
    }

    private fun wiredInput(): AudioDeviceInfo? = am.getDevices(AudioManager.GET_DEVICES_INPUTS).firstOrNull {
        it.type == AudioDeviceInfo.TYPE_WIRED_HEADSET || it.type == AudioDeviceInfo.TYPE_USB_HEADSET
    }

    /** Returns the preferred input device (null = default phone mic) and updates SCO routing. Call at silence boundaries. */
    fun select(): AudioDeviceInfo? {
        val bt = btInput()
        val allowBt = bt != null && when (policy()) {
            "always" -> true
            "when_no_media" -> !am.isMusicActive || (Build.VERSION.SDK_INT >= 31 && bt.type == AudioDeviceInfo.TYPE_BLE_HEADSET)
            else -> false
        }
        if (allowBt) {
            if (bt.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO) startSco(bt)
            current = if (Build.VERSION.SDK_INT >= 31 && bt.type == AudioDeviceInfo.TYPE_BLE_HEADSET) "bt_le" else "bt_sco"
            return bt
        }
        stopSco()
        wiredInput()?.let { current = "wired"; return it }
        current = "phone"
        return null
    }

    @Suppress("DEPRECATION")
    private fun startSco(device: AudioDeviceInfo) {
        if (scoActive) return
        if (Build.VERSION.SDK_INT >= 31) {
            val out = am.availableCommunicationDevices.firstOrNull { it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO && it.productName == device.productName }
                ?: am.availableCommunicationDevices.firstOrNull { it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO }
            scoActive = out != null && am.setCommunicationDevice(out)
        } else {
            am.startBluetoothSco()
            am.isBluetoothScoOn = true
            scoActive = true
        }
    }

    @Suppress("DEPRECATION")
    fun stopSco() {
        if (!scoActive) return
        if (Build.VERSION.SDK_INT >= 31) am.clearCommunicationDevice() else {
            am.isBluetoothScoOn = false
            am.stopBluetoothSco()
        }
        scoActive = false
    }
}
