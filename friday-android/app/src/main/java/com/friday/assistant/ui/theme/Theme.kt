package com.friday.assistant.ui.theme

import android.app.Activity
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat

private val DarkColorScheme = darkColorScheme(
    primary = Cyan,
    secondary = Dim,
    tertiary = Amber,
    background = Bg,
    surface = Surface,
    onPrimary = Bg,
    onSecondary = White,
    onTertiary = Bg,
    onBackground = White,
    onSurface = White,
    outline = Line,
    error = Danger,
)

@Composable
fun FridayTheme(content: @Composable () -> Unit) {
    val colorScheme = DarkColorScheme
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            window.statusBarColor = Bg.toArgb()
            window.navigationBarColor = Bg.toArgb()
            WindowCompat.getInsetsController(window, view).isAppearanceLightStatusBars = false
        }
    }
    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography(),
        content = content,
    )
}
