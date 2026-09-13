package com.pinebox.kiosk.kiosk

import android.app.admin.DeviceAdminReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.util.Log

/**
 * The device-owner hook.
 *
 * It requests no policies of its own (res/xml/device_admin.xml asks only
 * for force-lock). Its whole purpose is to exist so that
 *
 *     adb shell dpm set-device-owner com.pinebox.kiosk/.kiosk.PineDeviceAdminReceiver
 *
 * has a component to name. Being device owner is what turns startLockTask()
 * from "screen pinning, with a toast and a two-button escape gesture" into
 * a real kiosk the user cannot leave, and what lets the app pin itself as
 * the persistent HOME.
 */
class PineDeviceAdminReceiver : DeviceAdminReceiver() {

    override fun onEnabled(context: Context, intent: Intent) {
        super.onEnabled(context, intent)
        Log.i(TAG, "device admin enabled")
        /* Provisioning usually happens with the app already running (adb
         * dpm on a live device), so take the kiosk privileges immediately
         * rather than waiting for the next launch. */
        KioskController.applyOwnerPolicies(context)
    }

    override fun onDisabled(context: Context, intent: Intent) {
        super.onDisabled(context, intent)
        Log.w(TAG, "device admin disabled - the terminal is a tablet again")
    }

    companion object {
        private const val TAG = "PineDeviceAdmin"

        fun component(context: Context): ComponentName =
            ComponentName(context.applicationContext, PineDeviceAdminReceiver::class.java)
    }
}
