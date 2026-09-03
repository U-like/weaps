package dev.videomosaic.app

import android.app.Activity
import android.os.Bundle
import android.view.Gravity
import android.widget.LinearLayout
import android.widget.TextView

class MainActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val density = resources.displayMetrics.density
        val padding = (24 * density).toInt()

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(padding, padding, padding, padding)
        }

        root.addView(TextView(this).apply {
            text = "VideoMosaic"
            textSize = 28f
            gravity = Gravity.CENTER
        })

        root.addView(TextView(this).apply {
            text = "Android build environment is working."
            textSize = 16f
            gravity = Gravity.CENTER
            setPadding(0, (12 * density).toInt(), 0, 0)
        })

        setContentView(root)
    }
}
