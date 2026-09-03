#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

python3 - <<PY
import pathlib, xml.etree.ElementTree as ET
root = pathlib.Path(r"$PROJECT_ROOT")
for p in root.glob("app/src/main/**/*.xml"):
    ET.parse(p)
    print(f"[ok] XML {p.relative_to(root)}")
PY

mkdir -p "$TMP/src/android/app" "$TMP/src/android/os" "$TMP/src/android/view" \
         "$TMP/src/android/widget" "$TMP/src/android/content/res" "$TMP/src/android/util"

cat > "$TMP/src/android/os/Bundle.kt" <<'EOF'
package android.os
open class Bundle
EOF
cat > "$TMP/src/android/util/DisplayMetrics.kt" <<'EOF'
package android.util
class DisplayMetrics { var density: Float = 1f }
EOF
cat > "$TMP/src/android/content/res/Resources.kt" <<'EOF'
package android.content.res
import android.util.DisplayMetrics
class Resources { val displayMetrics: DisplayMetrics = DisplayMetrics() }
EOF
cat > "$TMP/src/android/app/Activity.kt" <<'EOF'
package android.app
import android.os.Bundle
import android.content.res.Resources
open class Activity {
    val resources: Resources = Resources()
    open fun onCreate(savedInstanceState: Bundle?) {}
    fun setContentView(view: Any?) {}
}
EOF
cat > "$TMP/src/android/view/Gravity.kt" <<'EOF'
package android.view
object Gravity { const val CENTER: Int = 17 }
EOF
cat > "$TMP/src/android/widget/LinearLayout.kt" <<'EOF'
package android.widget
class LinearLayout(val context: Any?) {
    var orientation: Int = 0
    var gravity: Int = 0
    fun setPadding(a: Int, b: Int, c: Int, d: Int) {}
    fun addView(view: Any?) {}
    companion object { const val VERTICAL: Int = 1 }
}
EOF
cat > "$TMP/src/android/widget/TextView.kt" <<'EOF'
package android.widget
class TextView(val context: Any?) {
    var text: CharSequence = ""
    var textSize: Float = 0f
    var gravity: Int = 0
    fun setPadding(a: Int, b: Int, c: Int, d: Int) {}
}
EOF

mapfile -t SOURCES < <(find "$TMP/src" "$PROJECT_ROOT/app/src/main/java" -type f -name '*.kt' | sort)
kotlinc "${SOURCES[@]}" -d "$TMP/out.jar"
test -s "$TMP/out.jar"
echo '[ok] Kotlin sources compile against local Android API stubs.'
