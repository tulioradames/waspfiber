package com.waspfiber.app

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Bundle
import android.os.Looper
import androidx.core.content.ContextCompat
import org.osmdroid.tileprovider.tilesource.OnlineTileSourceBase
import org.osmdroid.tileprovider.tilesource.TileSourceFactory
import org.osmdroid.util.MapTileIndex

// ---------------- sessao lembrada (token e e-mail; nunca a senha) ----------------
object Preferencias {
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("waspfiber", Context.MODE_PRIVATE)

    fun sessao(ctx: Context): Sessao? {
        val p = prefs(ctx)
        val token = p.getString("token", null) ?: return null
        return Sessao(token, p.getString("email", "")!!, p.getString("nome", "")!!,
                      p.getString("papel", "usuario")!!, p.getString("empresa", "")!!,
                      p.getString("empresa_nome", "")!!)
    }

    fun guardar(ctx: Context, s: Sessao) {
        prefs(ctx).edit().putString("token", s.token).putString("email", s.email)
            .putString("nome", s.nome).putString("papel", s.papel)
            .putString("empresa", s.empresa).putString("empresa_nome", s.empresaNome).apply()
    }

    fun esquecerToken(ctx: Context) = prefs(ctx).edit().remove("token").apply()

    fun ultimoEmail(ctx: Context): String = prefs(ctx).getString("email", "") ?: ""

    fun fonteMapa(ctx: Context): String = prefs(ctx).getString("fonte", "mapa") ?: "mapa"
    fun guardarFonteMapa(ctx: Context, fonte: String) =
        prefs(ctx).edit().putString("fonte", fonte).apply()
}

// ---------------- GPS ----------------
/** Ouve o GPS (e a rede, que acha mais rapido) e entrega cada posicao nova.
 *  Chamar parar() ao sair da tela. */
class Gps(private val ctx: Context, private val aoReceber: (Location) -> Unit) {
    private val gerente = ctx.getSystemService(Context.LOCATION_SERVICE) as LocationManager
    private val ouvinte = object : LocationListener {
        override fun onLocationChanged(local: Location) = aoReceber(local)
        @Deprecated("API antiga") override fun onStatusChanged(p: String?, s: Int, e: Bundle?) {}
        override fun onProviderEnabled(provider: String) {}
        override fun onProviderDisabled(provider: String) {}
    }

    @SuppressLint("MissingPermission")
    fun comecar(): Boolean {
        var algum = false
        for (prov in listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)) {
            try {
                if (gerente.isProviderEnabled(prov)) {
                    gerente.requestLocationUpdates(prov, 1000L, 0f, ouvinte, Looper.getMainLooper())
                    gerente.getLastKnownLocation(prov)?.let(aoReceber)
                    algum = true
                }
            } catch (_: SecurityException) {
            } catch (_: IllegalArgumentException) {
            }
        }
        return algum
    }

    fun parar() = try { gerente.removeUpdates(ouvinte) } catch (_: Exception) { }

    fun ligado(): Boolean = try {
        gerente.isProviderEnabled(LocationManager.GPS_PROVIDER) ||
            gerente.isProviderEnabled(LocationManager.NETWORK_PROVIDER)
    } catch (_: Exception) { false }
}

// ---------------- mapa ----------------
/** Satelite da Esri (o mesmo do programa de PC). O tile da Esri e z/y/x. */
object SateliteEsri : OnlineTileSourceBase(
    "EsriSatelite", 0, 18, 256, ".jpg",
    arrayOf("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/"),
    "Imagens © Esri, Maxar, Earthstar Geographics") {
    override fun getTileURLString(indice: Long): String =
        baseUrl + MapTileIndex.getZoom(indice) + "/" + MapTileIndex.getY(indice) + "/" +
            MapTileIndex.getX(indice)
}

fun fonteDeTiles(nome: String) = if (nome == "satelite") SateliteEsri else TileSourceFactory.MAPNIK

/** Cor e icone de cada tipo (os mesmos do programa de PC). */
object Tipos {
    val cores = mapOf("POP" to 0xFFB39DFA.toInt(), "CEO" to 0xFFF2B84B.toInt(),
                      "CTO" to 0xFF5AD18A.toInt())
    val icones = mapOf("POP" to R.drawable.ic_local_pop, "CEO" to R.drawable.ic_local_ceo,
                       "CTO" to R.drawable.ic_local_cto)
    const val COR_SEM_TIPO = 0xFF8B98A4.toInt()
    const val COR_DESTAQUE = 0xFF4DD0E1.toInt()

    /** Pino: gota na cor do tipo, contorno branco e o icone do tipo dentro. */
    fun pino(ctx: Context, tipo: String, escolhido: Boolean): Bitmap {
        val d = ctx.resources.displayMetrics.density
        val r = (if (escolhido) 17f else 14f) * d
        val margem = 6f * d
        val largura = (2 * r + 2 * margem).toInt()
        val altura = (2 * r + 16 * d + 2 * margem).toInt()
        val bmp = Bitmap.createBitmap(largura, altura, Bitmap.Config.ARGB_8888)
        val c = Canvas(bmp)
        val cx = largura / 2f
        val cy = margem + r
        val cor = cores[tipo] ?: COR_SEM_TIPO
        val tinta = Paint(Paint.ANTI_ALIAS_FLAG)
        if (escolhido) {
            tinta.style = Paint.Style.STROKE
            tinta.strokeWidth = 3.5f * d
            tinta.color = COR_DESTAQUE
            c.drawCircle(cx, cy, r + 3.5f * d, tinta)
        }
        val gota = Path().apply {
            moveTo(cx, altura - margem)
            lineTo(cx - r * 0.62f, cy + r * 0.55f)
            lineTo(cx + r * 0.62f, cy + r * 0.55f)
            close()
        }
        tinta.style = Paint.Style.FILL
        tinta.color = cor
        c.drawPath(gota, tinta)
        c.drawCircle(cx, cy, r, tinta)
        tinta.style = Paint.Style.STROKE
        tinta.strokeWidth = 2f * d
        tinta.color = 0xFFFFFFFF.toInt()
        c.drawCircle(cx, cy, r, tinta)
        icones[tipo]?.let { id ->
            ContextCompat.getDrawable(ctx, id)?.let { icone ->
                val lado = (r * 1.15f).toInt()
                icone.setBounds((cx - lado / 2).toInt(), (cy - lado / 2).toInt(),
                                (cx + lado / 2).toInt(), (cy + lado / 2).toInt())
                icone.draw(c)
            }
        }
        return bmp
    }
}
