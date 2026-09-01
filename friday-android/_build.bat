@echo off
set JAVA_HOME=C:\Program Files\Android\Android Studio\jbr
set ANDROID_HOME=C:\Users\PRINTARA\AppData\Local\Android\Sdk
cd /d F:\friday-kit\friday-android

echo === Generating wrapper with Gradle 9.5.1 ===
"C:\Users\PRINTARA\.gradle\wrapper\dists\gradle-9.5.1-bin\iq79hdu3mqx29lgffhp8bfmx\gradle-9.5.1\bin\gradle.bat" wrapper --gradle-version 9.5.1
if %ERRORLEVEL% NEQ 0 (
    echo Wrapper generation failed!
    exit /b 1
)

echo === Building debug APK ===
call gradlew.bat assembleDebug
if %ERRORLEVEL% NEQ 0 (
    echo Build failed!
    exit /b 1
)

echo === BUILD SUCCESS ===
echo APK location: app\build\outputs\apk\debug\app-debug.apk
dir /b app\build\outputs\apk\debug\app-debug.apk
