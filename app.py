"""
Agenda de Abastecimiento — versión Streamlit + Supabase
Accesible por link normal, sin necesidad de cuenta de Claude.
"""
import streamlit as st
from datetime import date, timedelta
from supabase import create_client, Client

st.set_page_config(page_title="Agenda de Abastecimiento", page_icon="📦", layout="wide")

DAYS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

STATUS_COLORS = {"urgente": "#C4321F", "proximo": "#B4720A", "postergado": "#6A4FCF", "aldia": "#1A8A4C"}
STATUS_BG = {"urgente": "#FCE9E6", "proximo": "#FBF0DA", "postergado": "#EDE8FC", "aldia": "#E1F5E9"}
STATUS_ORDER = {"urgente": 0, "proximo": 1, "postergado": 2, "aldia": 3}


# ---------------------------------------------------------------- connection
@st.cache_resource
def get_client() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


try:
    sb = get_client()
except Exception:
    st.error(
        "No se encontró la conexión a Supabase. Configura SUPABASE_URL y "
        "SUPABASE_KEY en Settings → Secrets de tu app en Streamlit Cloud."
    )
    st.stop()


# ---------------------------------------------------------------- data access
def fetch_providers():
    res = sb.table("providers").select("*").order("created_at").execute()
    return res.data or []


def fetch_historial():
    res = sb.table("historial").select("*").order("fecha", desc=True).limit(50).execute()
    return res.data or []


def insert_provider(row):
    sb.table("providers").insert(row).execute()


def update_provider(id_, patch):
    sb.table("providers").update(patch).eq("id", id_).execute()


def delete_provider(id_):
    sb.table("historial").delete().eq("provider_id", id_).execute()
    sb.table("providers").delete().eq("id", id_).execute()


def insert_historial(row):
    sb.table("historial").insert(row).execute()


# ---------------------------------------------------------------- status logic
def fmt(d):
    if not d:
        return "—"
    y, m, day = str(d)[:10].split("-")
    return f"{day}/{m}/{y}"


def compute_status(p):
    fecha_ultima = date.fromisoformat(str(p["fecha_ultima_oc"])[:10])
    frecuencia = int(p["frecuencia"])
    proxima = date.fromisoformat(str(p["proxima_revision"])[:10]) if p.get("proxima_revision") else None
    target = proxima or (fecha_ultima + timedelta(days=frecuencia))
    d = (date.today() - target).days
    if d >= 0:
        return {"key": "urgente", "label": "Debe realizar OC hoy: Sí",
                "detail": "Vence hoy" if d == 0 else f"{d} día(s) de atraso", "target": target}
    if d >= -3:
        return {"key": "proximo", "label": "Debe realizar OC hoy: No",
                "detail": f"Vence en {-d} día(s) ({fmt(target)})", "target": target}
    if proxima is not None:
        return {"key": "postergado", "label": "Debe realizar OC hoy: No",
                "detail": f"Postergado — revisión el {fmt(target)}", "target": target}
    return {"key": "aldia", "label": "Debe realizar OC hoy: No",
            "detail": f"Próxima OC estimada: {fmt(target)}", "target": target}


# ---------------------------------------------------------------- dialogs
@st.dialog("Proveedor")
def provider_dialog(existing=None):
    st.caption("Define su ciclo de compra para que la agenda calcule la próxima OC.")
    c1, c2 = st.columns(2)
    codigo = c1.text_input("Código", value=existing["codigo"] if existing else "", placeholder="PL0066")
    day = c2.selectbox("Día de revisión", DAYS,
                        index=DAYS.index(existing["day"]) if existing else 0)
    nombre = st.text_input("Nombre del proveedor", value=existing["nombre"] if existing else "",
                            placeholder="Tostaduría de café Delcafe")
    c3, c4 = st.columns(2)
    fecha = c3.date_input("Fecha última OC",
                           value=date.fromisoformat(str(existing["fecha_ultima_oc"])[:10]) if existing else date.today())
    frecuencia = c4.number_input("Frecuencia (días)", min_value=1,
                                  value=int(existing["frecuencia"]) if existing else 15)
    notas = st.text_area("Notas (opcional)", value=existing.get("notas", "") if existing else "")

    b1, b2 = st.columns([1, 1])
    if b1.button("Guardar", type="primary", use_container_width=True):
        if not codigo.strip() or not nombre.strip():
            st.warning("Completa código y nombre.")
        else:
            patch = {
                "day": day, "codigo": codigo.strip(), "nombre": nombre.strip(),
                "fecha_ultima_oc": fecha.isoformat(), "frecuencia": int(frecuencia),
                "notas": notas.strip(),
            }
            if existing:
                update_provider(existing["id"], patch)
            else:
                insert_provider(patch)
                insert_historial({
                    "provider_id": None, "fecha": date.today().isoformat(),
                    "accion": "creado", "responsable": st.session_state.get("mi_nombre", "—"),
                    "notas": "Registro inicial",
                })
            st.rerun()
    if existing and b2.button("Eliminar proveedor", use_container_width=True):
        delete_provider(existing["id"])
        st.rerun()


@st.dialog("Registrar acción")
def verify_dialog(p):
    status = compute_status(p)
    st.markdown(f"**{p['codigo']} · {p['nombre']}**")
    st.caption(f"Estado actual: {status['detail']} · Última OC: {fmt(p['fecha_ultima_oc'])} · "
               f"Frecuencia: {p['frecuencia']} días")

    choice = st.radio(
        "¿Qué pasó?",
        ["oc", "post"],
        format_func=lambda x: "✅ Ya se realizó la OC" if x == "oc" else "📅 Hay existencia — posponer",
        label_visibility="collapsed",
    )
    proxima = None
    if choice == "post":
        default_days = max(3, min(7, round(int(p["frecuencia"]) / 3)))
        proxima = st.date_input("Próxima fecha de revisión", value=date.today() + timedelta(days=default_days))

    responsable = st.text_input("Responsable", value=st.session_state.get("mi_nombre", ""))
    nota = st.text_input("Nota (opcional)", placeholder="Ej. quedan 3 semanas de stock")

    if st.button("Confirmar", type="primary", use_container_width=True):
        resp = responsable.strip() or "Sin nombre"
        if choice == "oc":
            update_provider(p["id"], {"fecha_ultima_oc": date.today().isoformat(), "proxima_revision": None})
            insert_historial({"provider_id": p["id"], "fecha": date.today().isoformat(),
                               "accion": "oc_realizada", "responsable": resp, "notas": nota.strip()})
        else:
            update_provider(p["id"], {"proxima_revision": proxima.isoformat()})
            insert_historial({"provider_id": p["id"], "fecha": date.today().isoformat(),
                               "accion": "postergado", "responsable": resp, "notas": nota.strip()})
        st.rerun()


# ---------------------------------------------------------------- UI
with st.sidebar:
    st.markdown("### 📦 Agenda de Abastecimiento")
    st.session_state.setdefault("mi_nombre", "")
    st.session_state["mi_nombre"] = st.text_input("Tu nombre", value=st.session_state["mi_nombre"])
    if st.button("🔄 Actualizar", use_container_width=True):
        st.rerun()
    st.caption(date.today().strftime("%A %d de %B, %Y").capitalize())
    if st.button("+ Agregar proveedor", use_container_width=True, type="primary"):
        provider_dialog(None)

providers = fetch_providers()

counts = {"urgente": 0, "proximo": 0, "postergado": 0, "aldia": 0}
for p in providers:
    counts[compute_status(p)["key"]] += 1

st.title("Agenda de Órdenes de Compra")
c1, c2, c3, c4 = st.columns(4)
c1.metric("🔴 Urgentes hoy", counts["urgente"])
c2.metric("🟠 Próximos (3 días)", counts["proximo"])
c3.metric("🟣 Postergados", counts["postergado"])
c4.metric("🟢 Al día", counts["aldia"])

filter_text = st.text_input("Buscar por código o nombre de proveedor…", "")

tabs = st.tabs(["Vista general"] + DAYS)

def render_list(day_filter, context):
    rows = providers if day_filter is None else [p for p in providers if p["day"] == day_filter]
    if filter_text.strip():
        f = filter_text.strip().lower()
        rows = [p for p in rows if f in p["codigo"].lower() or f in p["nombre"].lower()]
    rows = sorted(rows, key=lambda p: (STATUS_ORDER[compute_status(p)["key"]], compute_status(p)["target"]))

    if not rows:
        st.info("Nada por aquí todavía. Agrega un proveedor para empezar a llevar su ciclo de compra.")
        return

    for p in rows:
        status = compute_status(p)
        with st.container(border=True):
            cols = st.columns([2.6, 1, 1, 1.8, 1.4])
            with cols[0]:
                st.caption(p["codigo"])
                st.markdown(f"**{p['nombre']}**")
                st.caption(f"📌 {p['day']}")
            with cols[1]:
                st.caption("Última OC")
                st.write(fmt(p["fecha_ultima_oc"]))
            with cols[2]:
                st.caption("Frecuencia")
                st.write(f"{p['frecuencia']} días")
            with cols[3]:
                color, bg = STATUS_COLORS[status["key"]], STATUS_BG[status["key"]]
                st.markdown(
                    f"<div style='background:{bg};color:{color};padding:6px 10px;"
                    f"border-radius:8px;font-weight:700;font-size:13px;'>{status['label']}"
                    f"<br><span style='font-weight:500;font-size:11px;'>{status['detail']}</span></div>",
                    unsafe_allow_html=True,
                )
            with cols[4]:
                if st.button("Verificar / Actuar", key=f"verify_{context}_{p['id']}", use_container_width=True):
                    verify_dialog(p)
                if st.button("✎ Editar", key=f"edit_{context}_{p['id']}", use_container_width=True):
                    provider_dialog(p)

with tabs[0]:
    render_list(None, "general")
for i, day in enumerate(DAYS, start=1):
    with tabs[i]:
        render_list(day, day)

st.markdown("---")
st.subheader("🕒 Actividad reciente del equipo")
hist = [h for h in fetch_historial() if h["accion"] != "creado"]
if not hist:
    st.caption("Aún no hay acciones registradas por el equipo.")
else:
    id_to_provider = {p["id"]: p for p in providers}
    for h in hist[:10]:
        prov = id_to_provider.get(h["provider_id"])
        label = f"{prov['codigo']} · {prov['nombre']}" if prov else "(proveedor eliminado)"
        tag = "✅ OC realizada" if h["accion"] == "oc_realizada" else "📅 Postergado"
        st.markdown(f"**{label}** — {tag}  \n"
                    f"<span style='color:#5B6577;font-size:12.5px;'>{h['responsable']} · {fmt(h['fecha'])}"
                    f"{' · ' + h['notas'] if h['notas'] else ''}</span>", unsafe_allow_html=True)
