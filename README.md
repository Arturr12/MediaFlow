# MediaFlow

Aplicación de escritorio para Windows para administrar descargas y conversiones multimedia. Incluye conversión con FFmpeg, cola de tareas, miniaturas, perfiles de calidad y actualizaciones desde GitHub Releases.

## Repositorio oficial

- Propietario: `Arturr12`
- Repositorio: `MediaFlow`
- URL prevista: `https://github.com/Arturr12/MediaFlow`
- Visibilidad: **pública**, necesaria para que las instalaciones consulten Releases sin tokens ni credenciales.

## Estructura

- `app.py`: interfaz y lógica principal de MediaFlow.
- `updater.py`, `update_core.py`: comprobación, descarga y verificación de actualizaciones.
- `support/Install-Update.ps1`: aplica el instalador tras cerrar MediaFlow.
- `tools/create_update_manifest.py`: genera el manifiesto y SHA-256 del instalador.
- `tools/set_version.py`: actualiza la versión antes de preparar una publicación.
- `tools/build_release.py`: compila el EXE y el instalador en Windows.
- `.github/workflows/publish-release.yml`: construye el instalador y publica una GitHub Release al subir una etiqueta `vX.Y.Z`.

## Crear el repositorio por primera vez

1. Entra en https://github.com/new con la cuenta `Arturr12`.
2. Nombre: `MediaFlow`.
3. Descripción: `Aplicación de escritorio para descargas y conversión multimedia con actualizaciones automáticas.`
4. Selecciona **Public**.
5. No marques las opciones de crear README, `.gitignore` ni licencia; este paquete ya incluye sus archivos iniciales.
6. Pulsa **Create repository**.
7. Instala Git for Windows si aún no está instalado.
8. Abre esta carpeta y ejecuta `PUBLICAR-EN-GITHUB.bat`. Git Credential Manager puede abrir el navegador para iniciar sesión.

## Publicar la primera versión (0.4.4)

Después de que el código esté en la rama `main`:

1. Ejecuta `PUBLICAR-PRIMERA-RELEASE.bat`.
2. El script crea y sube la etiqueta `v0.4.4`.
3. GitHub Actions compila MediaFlow en Windows y publica una Release estable con:
   - `MediaFlow-Setup-0.4.4.exe`
   - `mediaflow-update.json`

Es importante publicar ambos assets en la misma Release. La aplicación usa `mediaflow-update.json` para validar versión, nombre, tamaño y SHA-256 del instalador.

## Publicar futuras versiones

1. Edita `RELEASE_NOTES.md` con las novedades reales.
2. Ejecuta `PUBLICAR-NUEVA-VERSION.bat` y escribe la siguiente versión, por ejemplo `0.4.5`.
3. El script actualiza las referencias de versión, crea un commit y sube la etiqueta `v0.4.5`.
4. GitHub Actions compila y publica la Release automáticamente.
5. Las instalaciones de MediaFlow comprueban GitHub al iniciar y cada seis horas. Si detectan una versión superior, muestran un aviso. La descarga y la instalación solo continúan con la autorización del usuario.

## Probar localmente

Windows 10/11 de 64 bits, Python 3.13 de 64 bits e Inno Setup 6 o 7:

```bat
run_portable.bat
```

Para crear un instalador manualmente:

```bat
build_installer.bat
```

## Seguridad del actualizador

- Solo consulta la API pública de GitHub por HTTPS.
- Solo acepta Releases estables, no borradores ni prereleases.
- Verifica SHA-256 antes de abrir el instalador.
- No almacena tokens de GitHub en los equipos de usuarios.
- No instala mientras existan descargas, conversiones o análisis activos.
- Para distribución pública amplia, se recomienda firmar el instalador con un certificado Authenticode. SHA-256 verifica integridad respecto del manifiesto publicado, pero no sustituye una firma digital independiente.

## Nota de distribución

Este repositorio publica el código fuente y los instaladores. No se agrega una licencia de reutilización automáticamente; define una licencia solo después de decidir los permisos que quieres conceder sobre el código de MediaFlow.
