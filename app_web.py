import streamlit as st
import streamlit.components.v1 as components
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from datetime import datetime
import pandas as pd
import os
import unicodedata
import traceback
import re

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Sistema POS Web", page_icon="🛒", layout="wide")

# --- FUNCIÓN PARA NORMALIZAR TEXTO ---
def normalizar_texto(texto):
    if not texto: return ""
    texto = str(texto)
    texto = unicodedata.normalize('NFD', texto)
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    return texto.upper().strip()

# --- CONFIGURACIÓN DE LA SUCURSAL ---
COLUMNAS_TIENDA = {
    "MI STORE CENTER": 4,  
    "GALERIA LA PAZ": 5,       
    "AZTLAN": 6,       
    "UYUSMARKET": 7        
}
CELDA_DOLAR_FILA = 2
CELDA_DOLAR_COL = 9        
COL_PRECIO_USD = 10        
COL_PRECIO_ADICIONAL = 11  

# ID DE GOOGLE DRIVE 
ID_CARPETA_BASE_DRIVE = "1Dm99RvDStOaWYJ5dxDgiFz9SpyzsNbwv"

# --- CONEXIÓN A GOOGLE SHEETS Y DRIVE (CACHEADO) ---
@st.cache_resource
def conectar_servicios():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    # En Render, asegúrate de que credenciales.json esté subido o en tus variables de entorno
    creds = ServiceAccountCredentials.from_json_keyfile_name("credenciales.json", scope)
    cliente = gspread.authorize(creds)
    # Cambia el enlace si tu hoja principal es diferente
    archivo = cliente.open_by_url("https://docs.google.com/spreadsheets/d/1Mfr5GShbSnToWSSzZohsfLQe9-LX4-zvTS1MY9WflIU/edit")
    
    try:
        drive_srv = build('drive', 'v3', credentials=creds)
    except Exception as e:
        drive_srv = None
        print(f"Error al conectar con Drive: {e}")
        
    return archivo, drive_srv

try:
    archivo, drive_service = conectar_servicios()
    hoja_inventario = archivo.worksheet("Inventario")
    hoja_historial = archivo.worksheet("Historial")
    hoja_usuarios = archivo.worksheet("Usuarios")
except Exception as e:
    st.error("🚨 Error al conectar con Google Sheets/Drive. Revisa los permisos.")
    st.code(traceback.format_exc())
    st.stop()

# --- FUNCIONES DE DRIVE ---
def crear_o_obtener_carpeta_drive(nombre_carpeta, id_padre):
    if not drive_service: return None
    try:
        query = f"mimeType='application/vnd.google-apps.folder' and name='{nombre_carpeta}' and trashed=false and '{id_padre}' in parents"
        res = drive_service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        archivos = res.get('files', [])
        if archivos:
            return archivos[0].get('id')
        else:
            meta = {'name': nombre_carpeta, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [id_padre]}
            carpeta = drive_service.files().create(body=meta, fields='id').execute()
            return carpeta.get('id')
    except Exception as e:
        print(f"Error creando carpeta en Drive: {e}")
        return None

def subir_archivo_drive(ruta_local, categoria_principal, tienda, nombre_carpeta_mes):
    if not drive_service or not ID_CARPETA_BASE_DRIVE: return
    try:
        id_categoria = crear_o_obtener_carpeta_drive(categoria_principal, ID_CARPETA_BASE_DRIVE)
        if not id_categoria: return
        
        id_padre_actual = id_categoria
        if tienda:
            id_tienda = crear_o_obtener_carpeta_drive(tienda, id_categoria)
            if not id_tienda: return
            id_padre_actual = id_tienda
            
        id_mes = crear_o_obtener_carpeta_drive(nombre_carpeta_mes, id_padre_actual)
        if not id_mes: return
            
        nombre_archivo = os.path.basename(ruta_local)
        file_metadata = {'name': nombre_archivo, 'parents': [id_mes]}
        mimetype = 'text/html' if ruta_local.endswith('.html') else 'text/plain'
        media = MediaFileUpload(ruta_local, mimetype=mimetype)
        
        drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    except Exception as e:
        print(f"Error subiendo archivo a Drive: {e}")

# --- VARIABLES DE SESIÓN ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'usuario' not in st.session_state: st.session_state.usuario = ""
if 'cargo' not in st.session_state: st.session_state.cargo = ""
if 'tienda' not in st.session_state: st.session_state.tienda = ""
if 'col_index' not in st.session_state: st.session_state.col_index = 0
if 'carrito' not in st.session_state: st.session_state.carrito = []
if 'ultimo_recibo_html' not in st.session_state: st.session_state.ultimo_recibo_html = ""

def cargar_datos_locales():
    datos_crudos = hoja_inventario.get_all_values()[1:]
    datos_comp = []
    for f in datos_crudos:
        f_ext = f + [""] * (3 - len(f)) if len(f) < 3 else f
        fila_norm = [normalizar_texto(f_ext[0]), normalizar_texto(f_ext[1]), normalizar_texto(f_ext[2])] + f_ext[3:]
        datos_comp.append(fila_norm)
    return datos_comp

if 'datos_completos' not in st.session_state: 
    st.session_state.datos_completos = cargar_datos_locales()

def obtener_fila_producto(datos_completos, nombre_producto):
    nombre_normalizado = normalizar_texto(nombre_producto)
    for i, fila in enumerate(datos_completos):
        if len(fila) > 2 and fila[2] == nombre_normalizado:
            return i + 2 
    return -1

def obtener_mes_actual():
    meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    return meses[datetime.now().month - 1], datetime.now().year

# --- 1. PANTALLA DE LOGIN ---
if not st.session_state.logged_in:
    st.markdown("<h1 style='text-align: center;'>🛒 Acceso al Sistema POS Web</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            user_input = st.text_input("USUARIO")
            pass_input = st.text_input("CONTRASEÑA", type="password")
            tienda_input = st.selectbox("SUCURSAL", list(COLUMNAS_TIENDA.keys()))
            submit_btn = st.form_submit_button("ACCEDER", use_container_width=True)
            
            if submit_btn:
                try:
                    usuarios_db = hoja_usuarios.get_all_records()
                    encontrado = False
                    for fila in usuarios_db:
                        if str(fila['Usuario']) == user_input and str(fila['Password']) == pass_input:
                            cargo = str(fila.get('Cargo', '')).upper()
                            
                            st.session_state.usuario = user_input
                            st.session_state.cargo = cargo
                            st.session_state.tienda = tienda_input
                            st.session_state.col_index = COLUMNAS_TIENDA[tienda_input]
                            st.session_state.logged_in = True
                            encontrado = True
                            break
                            
                    if encontrado:
                        st.rerun()
                    else:
                        st.error("Usuario o contraseña incorrectos")
                except Exception as e:
                    st.error(f"Error al conectar con la base de usuarios: {e}")

# --- 2. PANTALLA PRINCIPAL DEL SISTEMA ---
else:
    st.sidebar.title(f"🏬 {st.session_state.tienda}")
    st.sidebar.write(f"👤 **Cajero:** {st.session_state.usuario}")
    st.sidebar.write(f"🛡️ **Rol:** {st.session_state.cargo}")
    st.sidebar.divider()
    
    if st.sidebar.button("🔄 Actualizar Datos de la Nube", use_container_width=True):
        st.session_state.datos_completos = cargar_datos_locales()
        st.sidebar.success("Base de datos actualizada.")
        st.rerun()

    if st.sidebar.button("🚪 Cerrar Sesión", use_container_width=True):
        for key in list(st.session_state.keys()): del st.session_state[key]
        st.rerun()

    datos_completos = st.session_state.datos_completos
    categorias_unicas = [""] + sorted(list(set(f[0] for f in datos_completos if f[0])))
    try: valor_dolar_actual = float(hoja_inventario.cell(CELDA_DOLAR_FILA, CELDA_DOLAR_COL).value)
    except: valor_dolar_actual = 10.00

    tab_list = ["🛒 Punto de Venta", "📦 Traspasos"]
    if st.session_state.cargo == "JEFE": tab_list.append("⚙️ Panel de Jefe")
    tabs = st.tabs(tab_list)

    # ==========================================================
    # TAB 1: PUNTO DE VENTA
    # ==========================================================
    with tabs[0]:
        if st.session_state.ultimo_recibo_html != "":
            st.success("🎉 ¡Operación finalizada y guardada en el historial/drive!")
            components.html(st.session_state.ultimo_recibo_html, height=550, scrolling=True)
            
            c_btn1, c_btn2 = st.columns(2)
            with c_btn1:
                if st.button("⬅️ Iniciar Nueva Venta", type="primary", use_container_width=True):
                    st.session_state.ultimo_recibo_html = ""
                    st.rerun()
            with c_btn2:
                fecha_str_descarga = datetime.now().strftime("%Y%m%d_%H%M%S")
                st.download_button(
                    label="📥 Descargar Recibo (HTML)",
                    data=st.session_state.ultimo_recibo_html,
                    file_name=f"Documento_{fecha_str_descarga}.html",
                    mime="text/html",
                    use_container_width=True
                )
        else:
            col_izq, col_der = st.columns([5, 5])
            
            # --- PARTE IZQUIERDA: BUSCADOR Y CARRITO ---
            with col_izq:
                st.subheader("Buscador de Productos")
                
                f_cat, f_mar = st.columns(2)
                with f_cat: cat_sel = st.selectbox("Categoría:", categorias_unicas)
                with f_mar: 
                    marcas_disp = [""] + sorted(list(set(f[1] for f in datos_completos if f[0] == cat_sel and len(f)>1))) if cat_sel else [""]
                    mar_sel = st.selectbox("Marca:", marcas_disp)
                
                prods_disp = [""] + [f[2] for f in datos_completos if (not cat_sel or f[0] == cat_sel) and (not mar_sel or f[1] == mar_sel) and len(f)>2]
                prod_sel = st.selectbox("Modelo / Producto:", prods_disp)

                if prod_sel:
                    f_idx = obtener_fila_producto(datos_completos, prod_sel)
                    fila_datos = datos_completos[f_idx - 2]
                    
                    try: stk_local = int(fila_datos[st.session_state.col_index - 1]) if len(fila_datos) >= st.session_state.col_index and fila_datos[st.session_state.col_index - 1] else 0
                    except ValueError: stk_local = 0

                    s1 = fila_datos[COLUMNAS_TIENDA["MI STORE CENTER"]-1] if len(fila_datos) >= COLUMNAS_TIENDA["MI STORE CENTER"] else "0"
                    s2 = fila_datos[COLUMNAS_TIENDA["GALERIA LA PAZ"]-1] if len(fila_datos) >= COLUMNAS_TIENDA["GALERIA LA PAZ"] else "0"
                    s3 = fila_datos[COLUMNAS_TIENDA["AZTLAN"]-1] if len(fila_datos) >= COLUMNAS_TIENDA["AZTLAN"] else "0"
                    s4 = fila_datos[COLUMNAS_TIENDA["UYUSMARKET"]-1] if len(fila_datos) >= COLUMNAS_TIENDA["UYUSMARKET"] else "0"
                    
                    st.info(f"**MI STORE:** {s1} | **GALERIA:** {s2} | **AZTLAN:** {s3} | **UYUS:** {s4}")
                    
                    precio_usd = float(fila_datos[COL_PRECIO_USD - 1]) if len(fila_datos) >= COL_PRECIO_USD and fila_datos[COL_PRECIO_USD - 1] else 0.0
                    extra_bs = float(fila_datos[COL_PRECIO_ADICIONAL - 1]) if len(fila_datos) >= COL_PRECIO_ADICIONAL and fila_datos[COL_PRECIO_ADICIONAL - 1] else 0.0
                    
                    mayor_bs = precio_usd * valor_dolar_actual
                    menor_bs = mayor_bs + extra_bs
                    
                    c1, c2, c3 = st.columns([1,1.5,1.5])
                    with c1: cant = st.number_input("Cant", 1, stk_local if stk_local > 0 else 1, 1)
                    with c2: st.text_input("Mayor Bs (Ref)", f"{mayor_bs:.2f}", disabled=True)
                    with c3: cobro_u = st.number_input("Cobrar c/u (Bs)", 0.0, value=float(menor_bs))

                    if st.button("➕ Añadir al Carrito", type="primary", use_container_width=True):
                        if cant > stk_local:
                            st.error(f"Stock insuficiente en {st.session_state.tienda}. Stock actual: {stk_local}")
                        else:
                            subt_ref = cant * (mayor_bs + extra_bs)
                            subt_cobrado = cant * cobro_u
                            
                            st.session_state.carrito.append({
                                "producto": prod_sel, "cantidad": cant, 
                                "subtotal_ref": subt_ref, "subtotal_cobrado": subt_cobrado, 
                                "subtotal_usd": subt_cobrado / valor_dolar_actual if valor_dolar_actual > 0 else 0.0,
                                "diferencia": subt_cobrado - subt_ref
                            })
                            st.rerun()

                st.divider()
                st.subheader("📂 Cargar Cotización Pasada")
                cot_file = st.file_uploader("Sube un archivo .html de cotización:", type=["html"])
                if cot_file is not None:
                    if st.button("📥 Importar Productos al Carrito"):
                        contenido = cot_file.getvalue().decode("utf-8")
                        patron_v3 = r"<tr>\s*<td>(\d+)</td>\s*<td>(.*?)</td>\s*<td class=\"right\">([\d.]+)</td>\s*<td class=\"right\">([\d.]+)</td>\s*<td class=\"right\">([\d.]+)</td>\s*<td class=\"right\">([\d.]+)</td>\s*</tr>"
                        patron_v2 = r"<tr>\s*<td>(\d+)</td>\s*<td>(.*?)</td>\s*<td class=\"right\">([\d.]+)</td>\s*<td class=\"right\">([\d.]+)</td>\s*<td class=\"right\">([\d.]+)</td>\s*</tr>"
                        patron_v1 = r"<tr>\s*<td>(\d+)</td>\s*<td>(.*?)</td>\s*<td class=\"right\">([\d.]+)</td>\s*<td class=\"right\">([\d.]+)</td>\s*</tr>"
                        
                        matches = re.findall(patron_v3, contenido)
                        tipo_patron = 3
                        if not matches: matches = re.findall(patron_v2, contenido); tipo_patron = 2
                        if not matches: matches = re.findall(patron_v1, contenido); tipo_patron = 1
                        
                        if not matches:
                            st.error("No se encontraron productos válidos en este archivo HTML.")
                        else:
                            st.session_state.carrito = []
                            prods_no_enc = []
                            for match in matches:
                                if tipo_patron == 3: cant_str, prod_nombre, _, _, bs_str, _ = match
                                elif tipo_patron == 2: cant_str, prod_nombre, _, bs_str, _ = match
                                else: cant_str, prod_nombre, bs_str, _ = match
                                
                                cantidad = int(cant_str)
                                producto = normalizar_texto(prod_nombre)
                                subt_cob = float(bs_str)
                                
                                fila_idx = obtener_fila_producto(datos_completos, producto)
                                if fila_idx == -1:
                                    prods_no_enc.append(producto)
                                    continue
                                
                                f_dat = datos_completos[fila_idx - 2]
                                p_usd = float(f_dat[COL_PRECIO_USD-1]) if len(f_dat)>=COL_PRECIO_USD and f_dat[COL_PRECIO_USD-1] else 0.0
                                e_bs = float(f_dat[COL_PRECIO_ADICIONAL-1]) if len(f_dat)>=COL_PRECIO_ADICIONAL and f_dat[COL_PRECIO_ADICIONAL-1] else 0.0
                                
                                subt_ref = cantidad * ((p_usd * valor_dolar_actual) + e_bs)
                                
                                st.session_state.carrito.append({
                                    "producto": producto, "cantidad": cantidad,
                                    "subtotal_ref": subt_ref, "subtotal_cobrado": subt_cob,
                                    "subtotal_usd": subt_cob / valor_dolar_actual if valor_dolar_actual > 0 else 0.0,
                                    "diferencia": subt_cob - subt_ref
                                })
                            if prods_no_enc:
                                st.warning("Algunos productos ya no existen en la base de datos: " + ", ".join(prods_no_enc))
                            st.rerun()

            # --- PARTE DERECHA: CARRITO Y COBRO ---
            with col_der:
                st.subheader("🛒 Carrito Actual")
                if not st.session_state.carrito:
                    st.info("El carrito está vacío.")
                else:
                    # GESTIÓN INDIVIDUAL DEL CARRITO (Editar / Eliminar específico)
                    for idx, item in enumerate(st.session_state.carrito):
                        c_prod, c_cant, c_bs, c_del = st.columns([4, 2, 2, 1])
                        c_prod.markdown(f"**{item['producto']}**")
                        
                        # Edición directa de cantidad
                        nueva_cant = c_cant.number_input("Cant", min_value=1, value=item['cantidad'], key=f"edit_cant_{idx}")
                        if nueva_cant != item['cantidad']:
                            f_idx = obtener_fila_producto(datos_completos, item['producto'])
                            stk_act = int(datos_completos[f_idx-2][st.session_state.col_index-1]) if f_idx != -1 else 0
                            if nueva_cant > stk_act:
                                st.error(f"Stock insuficiente ({stk_act} disponibles)")
                            else:
                                pu_cob = item['subtotal_cobrado'] / item['cantidad']
                                pu_ref = item['subtotal_ref'] / item['cantidad']
                                item['cantidad'] = nueva_cant
                                item['subtotal_cobrado'] = pu_cob * nueva_cant
                                item['subtotal_ref'] = pu_ref * nueva_cant
                                item['subtotal_usd'] = item['subtotal_cobrado'] / valor_dolar_actual if valor_dolar_actual > 0 else 0.0
                                item['diferencia'] = item['subtotal_cobrado'] - item['subtotal_ref']
                                st.rerun()
                                
                        c_bs.write(f"{item['subtotal_cobrado']:.2f} Bs")
                        
                        # Eliminar producto específico
                        if c_del.button("🗑️", key=f"del_{idx}"):
                            st.session_state.carrito.pop(idx)
                            st.rerun()

                    t_ref = sum(i["subtotal_ref"] for i in st.session_state.carrito)
                    t_real = sum(i["subtotal_cobrado"] for i in st.session_state.carrito)
                    t_usd = sum(i["subtotal_usd"] for i in st.session_state.carrito)

                    st.markdown("---")
                    col_t1, col_t2 = st.columns(2)
                    col_t1.metric("TOTAL REFERENCIAL (Bs)", f"{t_ref:.2f}")
                    col_t2.metric("TOTAL A COBRAR (Bs)", f"{t_real:.2f}", f"${t_usd:.2f} USD", delta_color="off")
                    
                    if st.button("🗑️ Vaciar Todo el Carrito", use_container_width=True):
                        st.session_state.carrito = []
                        st.rerun()

                    # --- BLOQUE DE PAGOS Y FINALIZACIÓN DE VENTA ---
                    st.markdown("---")
                    st.subheader("💳 Finalizar Operación")
                    
                    tipo_op = st.radio("Selecciona el tipo de operación:", ["Venta Normal", "Venta con Observación", "Cotización"], horizontal=True)
                    obs_texto = ""
                    if tipo_op == "Venta con Observación":
                        obs_texto = st.text_input("⚠️ Escribe la observación obligatoria:")

                    if tipo_op == "Cotización":
                        if st.button("📝 GENERAR COTIZACIÓN", type="primary", use_container_width=True):
                            fecha_h = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            html_cot = f"""
                            <div style="font-family:'Courier New', monospace; background:white; color:black; width:100%; max-width:400px; margin:0 auto; padding:20px; border-radius:5px; border: 2px dashed #FF9800;">
                                <h2 style="text-align:center; color:#E65100;">{st.session_state.tienda}</h2>
                                <div style="text-align:center; font-size:12px; color:#666;">COTIZACIÓN DE PRECIOS<br>Fecha: {fecha_h}<br>Atendido por: {st.session_state.usuario}</div>
                                <hr style="border-top:1px dashed #999;">
                                <table style="width:100%; font-size:13px; border-collapse:collapse;">
                                    <tr style="background:#f0f0f0; border-bottom:2px solid #555;"><th>Cant</th><th>Producto</th><th style="text-align:right;">P.Unit Bs</th><th style="text-align:right;">P.Unit $us</th><th style="text-align:right;">Subt. Bs</th><th style="text-align:right;">Subt. $us</th></tr>
                            """
                            for i in st.session_state.carrito:
                                pu_bs = i['subtotal_cobrado'] / i['cantidad'] if i['cantidad']>0 else 0
                                pu_usd = i['subtotal_usd'] / i['cantidad'] if i['cantidad']>0 else 0
                                html_cot += f"<tr><td style='text-align:center; border:1px solid #aaa;'>{i['cantidad']}</td><td style='border:1px solid #aaa;'>{i['producto']}</td><td style='text-align:right; border:1px solid #aaa;'>{pu_bs:.2f}</td><td style='text-align:right; border:1px solid #aaa;'>{pu_usd:.2f}</td><td style='text-align:right; border:1px solid #aaa;'>{i['subtotal_cobrado']:.2f}</td><td style='text-align:right; border:1px solid #aaa;'>{i['subtotal_usd']:.2f}</td></tr>"
                            html_cot += f"""
                                </table><hr style="border-top:1px dashed #999;">
                                <table style="width:100%; font-size:16px; font-weight:bold;">
                                    <tr><td>TOTAL Bs:</td><td style="text-align:right;">{t_real:.2f}</td></tr>
                                    <tr><td>TOTAL $us:</td><td style="text-align:right;">{t_usd:.2f}</td></tr>
                                </table>
                                <div style="text-align:center; font-size:12px; color:#D32F2F; font-weight:bold; margin-top:15px;">Teléfonos de ref: 75295017 - 78851301<br>DOCUMENTO NO VÁLIDO COMO RECIBO<br>*Precios sujetos a cambio*</div>
                            </div>
                            """
                            
                            mes, anio = obtener_mes_actual()
                            t_segura = st.session_state.tienda.replace(" ", "_")
                            c_mes = f"COTIZACIONES_{mes.upper()}_{anio}"
                            ruta_tmp = f"Cotizacion_{t_segura}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
                            with open(ruta_tmp, "w", encoding="utf-8") as f: f.write(html_cot)
                            subir_archivo_drive(ruta_tmp, "COTIZACIONES", st.session_state.tienda, c_mes)
                            
                            st.session_state.ultimo_recibo_html = html_cot
                            st.session_state.carrito = []
                            st.rerun()
                    else:
                        st.markdown("#### Selecciona el Método de Pago")
                        c_f1, c_f2 = st.columns(2)
                        btn_efe = c_f1.button("💵 100% EFECTIVO", use_container_width=True)
                        btn_qr = c_f2.button("📱 100% QR", use_container_width=True)
                        
                        with st.expander("💸 Opción: Pago Mixto (Combinado)", expanded=False):
                            st.write("Ingresa los montos exactos recibidos en cada método:")
                            c_m1, c_m2, c_m3 = st.columns(3)
                            with c_m1: m_efe = st.number_input("Efectivo (Bs)", 0.0)
                            with c_m2: m_qr = st.number_input("QR (Bs)", 0.0)
                            with c_m3: m_usd = st.number_input("Dólares ($us)", 0.0)
                            btn_mixto = st.button("✅ Procesar Pago Mixto", use_container_width=True)

                        metodo_final = ""
                        p_efe = 0.0; p_qr = 0.0; p_usd = 0.0
                        
                        if btn_efe: metodo_final = "EFECTIVO"; p_efe = t_real
                        elif btn_qr: metodo_final = "QR"; p_qr = t_real
                        elif btn_mixto:
                            if round(m_efe + m_qr + (m_usd * valor_dolar_actual), 2) < round(t_real, 2):
                                st.error(f"El pago mixto es menor al Total a Cobrar.")
                            else:
                                metodo_final = f"MIXTO (Efe: {m_efe:.2f} Bs | QR: {m_qr:.2f} Bs | USD: {m_usd:.2f} $us)"
                                p_efe = m_efe; p_qr = m_qr; p_usd = m_usd

                        if metodo_final != "":
                            if tipo_op == "Venta con Observación" and not obs_texto:
                                st.error("Debes escribir una observación obligatoria.")
                            else:
                                fecha_h = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                filas_h = []
                                for item in st.session_state.carrito:
                                    idx = obtener_fila_producto(datos_completos, item["producto"])
                                    s_act = int(hoja_inventario.cell(idx, st.session_state.col_index).value or 0)
                                    hoja_inventario.update_cell(idx, st.session_state.col_index, s_act - item["cantidad"])
                                    
                                    # Proporción matemática para las 12 columnas exactas
                                    ratio = item['subtotal_cobrado'] / t_real if t_real > 0 else 0
                                    i_qr = round(p_qr * ratio, 2)
                                    i_efe = round(p_efe * ratio, 2)
                                    i_usd = round(p_usd * ratio, 2)
                                    i_mixto = round(i_qr + i_efe + (i_usd * valor_dolar_actual), 2)
                                    
                                    txt_mov = f"-{item['cantidad']} (VENTA)"
                                    if obs_texto: txt_mov += f" [OBS: {obs_texto}]"
                                    txt_mov += f" [PAGO: {metodo_final}]"
                                    
                                    filas_h.append([
                                        fecha_h, st.session_state.tienda, item["producto"], txt_mov, st.session_state.usuario,
                                        round(item['subtotal_ref'], 2), round(item['diferencia'], 2), round(item['subtotal_cobrado'], 2),
                                        i_qr, i_efe, i_mixto, i_usd
                                    ])
                                hoja_historial.append_rows(filas_h)
                                
                                # RECIBO HTML
                                html_venta = f"""
                                <div style="font-family:'Courier New', monospace; background:white; color:black; width:100%; max-width:400px; margin:0 auto; padding:20px; border-radius:5px; border: 1px solid #ccc;">
                                    <h2 style="text-align:center;">{st.session_state.tienda}</h2>
                                    <div style="text-align:center; font-size:12px; color:#666;">COMPROBANTE DE VENTA<br>Fecha: {fecha_h}<br>Cajero: {st.session_state.usuario}<br>Método: <strong>{metodo_final}</strong></div>
                                    <hr style="border-top:1px dashed #999;">
                                    <table style="width:100%; font-size:13px; border-collapse:collapse;">
                                        <tr style="background:#f0f0f0; border-bottom:2px solid #555;"><th>Cant</th><th>Producto</th><th style="text-align:right;">P.Unit Bs</th><th style="text-align:right;">P.Unit $us</th><th style="text-align:right;">Subt. Bs</th><th style="text-align:right;">Subt. $us</th></tr>
                                """
                                for i in st.session_state.carrito:
                                    pu_bs = i['subtotal_cobrado'] / i['cantidad'] if i['cantidad']>0 else 0
                                    pu_usd = i['subtotal_usd'] / i['cantidad'] if i['cantidad']>0 else 0
                                    html_venta += f"<tr><td style='text-align:center; border:1px solid #aaa;'>{i['cantidad']}</td><td style='border:1px solid #aaa;'>{i['producto']}</td><td style='text-align:right; border:1px solid #aaa;'>{pu_bs:.2f}</td><td style='text-align:right; border:1px solid #aaa;'>{pu_usd:.2f}</td><td style='text-align:right; border:1px solid #aaa;'>{i['subtotal_cobrado']:.2f}</td><td style='text-align:right; border:1px solid #aaa;'>{i['subtotal_usd']:.2f}</td></tr>"
                                html_venta += f"""
                                    </table><hr style="border-top:1px dashed #999;">
                                    <table style="width:100%; font-size:16px; font-weight:bold;">
                                        <tr><td>TOTAL Bs:</td><td style="text-align:right;">{t_real:.2f}</td></tr>
                                        <tr><td>TOTAL $us:</td><td style="text-align:right;">{t_usd:.2f}</td></tr>
                                    </table>
                                    <div style="text-align:center; font-size:12px; color:#666; margin-top:15px;">Teléfonos de ref: 75295017 - 78851301<br>¡Gracias por su preferencia!<br>Vuelva pronto.</div>
                                </div>
                                """
                                
                                mes, anio = obtener_mes_actual()
                                t_segura = st.session_state.tienda.replace(" ", "_")
                                c_mes = f"COMPROBANTES_{mes.upper()}_{anio}"
                                ruta_tmp = f"Factura_{t_segura}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
                                with open(ruta_tmp, "w", encoding="utf-8") as f: f.write(html_venta)
                                subir_archivo_drive(ruta_tmp, "COMPROBANTES", st.session_state.tienda, c_mes)

                                st.session_state.ultimo_recibo_html = html_venta
                                st.session_state.carrito = []
                                st.session_state.datos_completos = cargar_datos_locales()
                                st.rerun()

    # ==========================================================
    # TAB 2: TRASPASOS Y ENVÍOS
    # ==========================================================
    with tabs[1]:
        st.header("📦 Enviar Productos a otra Sucursal o Departamento")
        prods_totales = [""] + [f[2] for f in datos_completos if len(f)>2 and f[2]]
        prod_t = st.selectbox("Selecciona el producto:", prods_totales, key="tras_prod")
        
        if prod_t:
            idx_t = obtener_fila_producto(datos_completos, prod_t)
            fila_datos = hoja_inventario.row_values(idx_t)
            try: stk_disp = int(fila_datos[st.session_state.col_index - 1]) if len(fila_datos) >= st.session_state.col_index and fila_datos[st.session_state.col_index - 1] else 0
            except ValueError: stk_disp = 0
                
            texto_stock_info = f"**SUCURSAL ACTUAL \"{st.session_state.tienda}\": {stk_disp}**"
            otras_suc = []
            for nombre_suc, col_suc in COLUMNAS_TIENDA.items():
                if nombre_suc != st.session_state.tienda:
                    try: val_s = int(fila_datos[col_suc - 1]) if len(fila_datos) >= col_suc and fila_datos[col_suc - 1] else 0
                    except ValueError: val_s = 0
                    otras_suc.append(f"{nombre_suc}={val_s}")
            
            if otras_suc: texto_stock_info += "  |  " + "  |  ".join(otras_suc)
            st.info(texto_stock_info)
            
            destinos = [s for s in COLUMNAS_TIENDA.keys() if s != st.session_state.tienda] + ["Beni", "Sucre", "Cochabamba", "Oruro", "Pando", "Potosí", "Santa Cruz de la Sierra", "Tarija"]
            t_dest = st.selectbox("Sucursal / Departamento Destino:", destinos)
            t_cant = st.number_input("Cantidad a Enviar:", 1, stk_disp if stk_disp > 0 else 1, 1)
            
            if st.button("🚚 Confirmar Envío / Traspaso", type="primary"):
                if t_cant > stk_disp: st.error("No tienes suficiente stock para enviar.")
                else:
                    col_origen = st.session_state.col_index
                    val_orig = hoja_inventario.cell(idx_t, col_origen).value
                    hoja_inventario.update_cell(idx_t, col_origen, (int(val_orig) if val_orig else 0) - t_cant)
                    
                    fh = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    if t_dest in COLUMNAS_TIENDA:
                        col_destino = COLUMNAS_TIENDA[t_dest]
                        val_dest = hoja_inventario.cell(idx_t, col_destino).value
                        hoja_inventario.update_cell(idx_t, col_destino, (int(val_dest) if val_dest else 0) + t_cant)
                        
                        hoja_historial.append_row([fh, st.session_state.tienda, prod_t, f"-{t_cant} (TRASPASO A {t_dest})", st.session_state.usuario, 0,0,0,0,0,0,0])
                        hoja_historial.append_row([fh, t_dest, prod_t, f"+{t_cant} (TRASPASO DE {st.session_state.tienda})", st.session_state.usuario, 0,0,0,0,0,0,0])
                        st.success(f"Traspaso interno hacia {t_dest} completado.")
                    else:
                        hoja_historial.append_row([fh, st.session_state.tienda, prod_t, f"-{t_cant} (ENVIO A {t_dest.upper()})", st.session_state.usuario, 0,0,0,0,0,0,0])
                        st.success(f"Envío de mercadería hacia {t_dest} registrado correctamente.")
                        
                    st.session_state.datos_completos = cargar_datos_locales()
                    st.rerun()

    # ==========================================================
    # TAB 3: JEFE (ADMINISTRACIÓN Y REPORTES)
    # ==========================================================
    if st.session_state.cargo == "JEFE":
        with tabs[2]:
            st.header("⚙️ Panel de Control - Administrador")
            
            with st.expander("💰 Configuración de Precios", expanded=True):
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    n_dol = st.number_input("Cotización Dólar (Bs/USD)", value=float(valor_dolar_actual))
                    if st.button("Actualizar Dólar Global"):
                        hoja_inventario.update_cell(CELDA_DOLAR_FILA, CELDA_DOLAR_COL, n_dol)
                        st.success("Dólar actualizado."); st.rerun()
                        
                with col_d2:
                    p_conf = st.selectbox("Elegir Producto para cambiar precio:", [""] + [f[2] for f in datos_completos if len(f)>2], key="conf_p")
                    if p_conf:
                        idx_c = obtener_fila_producto(datos_completos, p_conf)
                        fila_c = hoja_inventario.row_values(idx_c)
                        v_usd = float(fila_c[COL_PRECIO_USD-1]) if len(fila_c)>=COL_PRECIO_USD and fila_c[COL_PRECIO_USD-1] else 0.0
                        v_ext = float(fila_c[COL_PRECIO_ADICIONAL-1]) if len(fila_c)>=COL_PRECIO_ADICIONAL and fila_c[COL_PRECIO_ADICIONAL-1] else 0.0
                        
                        n_usd = st.number_input("Precio USD Base ($):", value=v_usd)
                        n_ext = st.number_input("Extra para Menor (Bs):", value=v_ext)
                        if st.button("Guardar Precios"):
                            hoja_inventario.update_cell(idx_c, COL_PRECIO_USD, n_usd)
                            hoja_inventario.update_cell(idx_c, COL_PRECIO_ADICIONAL, n_ext)
                            st.success("Precios guardados."); st.session_state.datos_completos = cargar_datos_locales(); st.rerun()

            with st.expander("📦 Ajuste Directo de Stock"):
                p_aj = st.selectbox("Modificar inventario de:", [""] + [f[2] for f in datos_completos if len(f)>2], key="aj_p")
                if p_aj:
                    idx_aj = obtener_fila_producto(datos_completos, p_aj)
                    fila_datos_aj = hoja_inventario.row_values(idx_aj)
                    
                    suc_elegida = st.selectbox("Seleccione la Sucursal a afectar:", list(COLUMNAS_TIENDA.keys()))
                    col_afectada = COLUMNAS_TIENDA[suc_elegida]
                    
                    try: s_loc = int(fila_datos_aj[col_afectada - 1]) if len(fila_datos_aj) >= col_afectada and fila_datos_aj[col_afectada - 1] else 0
                    except ValueError: s_loc = 0
                        
                    st.info(f"**Stock actual en {suc_elegida}: {s_loc}**")
                    
                    c_aj = st.number_input("Unidades a ajustar:", 1, value=1)
                    c_sum, c_res = st.columns(2)
                    if c_sum.button("⬆️ Agregar Stock"):
                        hoja_inventario.update_cell(idx_aj, col_afectada, s_loc + c_aj)
                        hoja_historial.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), suc_elegida, p_aj, f"+{c_aj} (AGREGA STOCK)", st.session_state.usuario, 0,0,0,0,0,0,0])
                        st.success("Agregado con éxito."); st.session_state.datos_completos = cargar_datos_locales(); st.rerun()
                    if c_res.button("⬇️ Retirar Stock"):
                        if s_loc - c_aj < 0: st.error("El stock no puede ser negativo.")
                        else:
                            hoja_inventario.update_cell(idx_aj, col_afectada, s_loc - c_aj)
                            hoja_historial.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), suc_elegida, p_aj, f"-{c_aj} (STOCK CORREGIDO)", st.session_state.usuario, 0,0,0,0,0,0,0])
                            st.success("Retirado con éxito."); st.session_state.datos_completos = cargar_datos_locales(); st.rerun()

            with st.expander("📊 Reportes y Extractos Bancarios", expanded=True):
                st.subheader("Extracto Global (Todas las Tiendas)")
                if st.button("🌍 Generar Extracto Global de Hoy", type="primary"):
                    h_datos = hoja_historial.get_all_values()[1:]
                    hoy = datetime.now().strftime("%Y-%m-%d")
                    ahora = datetime.now().strftime("%H-%M-%S")
                    mes, anio = obtener_mes_actual()
                    
                    filas_html = ""
                    t_txt = f"📦 EXTRACTO DE MOVIMIENTOS GLOBALES - {hoy}\n{'='*80}\n"
                    rep_mov = {s: {"Entradas": [], "Salidas": [], "Ventas": []} for s in COLUMNAS_TIENDA.keys()}
                    
                    for f in h_datos:
                        if len(f) < 5: continue
                        if hoy in f[0]:
                            mov = f[3]; c_css = "color:#2E7D32;" if mov.startswith("+") else "color:#D32F2F;"
                            filas_html += f"<tr><td>{f[0]}</td><td>{f[1]}</td><td>{f[2]}</td><td style='{c_css} font-weight:bold;'>{mov}</td><td>{f[4]}</td></tr>"
                            t_loc = f[1]
                            if t_loc in rep_mov:
                                if "(TRASPASO DE" in mov or "(AGREGA STOCK)" in mov or (mov.startswith("+") and "(AJUSTE)" in mov):
                                    rep_mov[t_loc]["Entradas"].append(f"{f[2]}: {mov} ({f[4]})")
                                elif "(TRASPASO A" in mov or "(STOCK CORREGIDO)" in mov or (mov.startswith("-") and "(AJUSTE)" in mov):
                                    rep_mov[t_loc]["Salidas"].append(f"{f[2]}: {mov} ({f[4]})")
                                elif "(VENTA)" in mov or (mov.startswith("-") and "(" not in mov):
                                    rep_mov[t_loc]["Ventas"].append(f"{f[2]}: {mov} ({f[4]})")
                    
                    for s, d in rep_mov.items():
                        t_txt += f"\n🏠 SUCURSAL: {s}\n{'-'*75}\n🟢 ENTRADAS:\n"
                        for x in d["Entradas"]: t_txt += f"  • {x}\n"
                        t_txt += "\n🔴 SALIDAS:\n"
                        for x in d["Salidas"]: t_txt += f"  • {x}\n"
                        t_txt += "\n🛒 VENTAS:\n"
                        for x in d["Ventas"]: t_txt += f"  • {x}\n"
                        t_txt += "="*75 + "\n"
                        
                    html_final = f"""
                    <div style="font-family:sans-serif; background:white; color:black; padding:20px; border-radius:8px;">
                        <h2 style="color:#2E7D32; border-bottom:3px solid #4CAF50;">Extracto de Entradas y Salidas</h2>
                        <table style="width:100%; border-collapse:collapse; font-size:14px; text-align:left;">
                            <tr style="background:#4CAF50; color:white;"><th>Fecha</th><th>Tienda</th><th>Producto</th><th>Movimiento</th><th>Cajero</th></tr>
                            {filas_html if filas_html else "<tr><td colspan='5' style='text-align:center;'>Sin movimientos hoy</td></tr>"}
                        </table>
                    </div>
                    """
                    
                    r_tmp = f"Extracto_{hoy}_{ahora}.html"
                    with open(r_tmp, "w", encoding="utf-8") as file: file.write(html_final)
                    subir_archivo_drive(r_tmp, "ENTRADAS Y SALIDAS", "", f"ENTRADAS_SALIDAS_{mes.upper()}_{anio}")
                    
                    components.html(html_final, height=400, scrolling=True)
                    st.download_button("📥 Descargar Extracto HTML", html_final, file_name=r_tmp, mime="text/html")
                    st.download_button("📥 Descargar Extracto TXT", t_txt, file_name=f"Extracto_{hoy}.txt")

                st.divider()
                st.subheader("Reporte Diario de Ventas por Sucursal")
                t_rep = st.selectbox("Consultar tienda:", list(COLUMNAS_TIENDA.keys()))
                if st.button("Generar Reporte de Ventas"):
                    h_datos = hoja_historial.get_all_values()[1:]
                    hoy = datetime.now().strftime("%Y-%m-%d")
                    ahora = datetime.now().strftime("%H-%M-%S")
                    
                    r_detallado = {}; t_cant = 0; t_cob_bs = 0.0; t_qr = 0.0; t_efe_bs = 0.0; t_efe_usd = 0.0
                    
                    for f in h_datos:
                        if len(f)<5: continue
                        if hoy in f[0] and f[1] == t_rep and ("(VENTA)" in f[3] or (f[3].startswith("-") and "(" not in f[3])):
                            try: cant = abs(int(f[3].split()[0]))
                            except ValueError: continue
                            
                            subt_cobrado = float(f[7]) if len(f)>7 and f[7] else 0.0
                            qr_bs = float(f[8]) if len(f)>8 and f[8] else 0.0
                            efe_bs = float(f[9]) if len(f)>9 and f[9] else 0.0
                            efe_usd = float(f[11]) if len(f)>11 and f[11] else 0.0
                            
                            vend = f[4]; prod = f[2]
                            if vend not in r_detallado: r_detallado[vend] = {'t_cobrado': 0.0, 'prods': {}}
                            if prod not in r_detallado[vend]['prods']: r_detallado[vend]['prods'][prod] = {'cant': 0, 'bs': 0.0}
                            
                            r_detallado[vend]['prods'][prod]['cant'] += cant
                            r_detallado[vend]['prods'][prod]['bs'] += subt_cobrado
                            r_detallado[vend]['t_cobrado'] += subt_cobrado
                            
                            t_cant += cant; t_cob_bs += subt_cobrado; t_qr += qr_bs; t_efe_bs += efe_bs; t_efe_usd += efe_usd

                    txt = f"📊 INFORME DETALLADO DE VENTAS - {hoy} {ahora}\nSucursal: {t_rep}\nGenerado por: {usuario_actual}\n{'='*45}\n\n"
                    if not r_detallado: txt += "No hay ventas registradas hoy."
                    else:
                        for v, dat in r_detallado.items():
                            txt += f"👤 VENDEDOR: {v}\n"
                            for p, inf in dat['prods'].items():
                                txt += f"  • {p}: {inf['cant']} u. -> {inf['bs']:.2f} Bs\n"
                            txt += f"  ----------------------\n  💰 TOTAL COBRADO : {dat['t_cobrado']:.2f} Bs\n{'='*45}\n"
                        txt += f"\n📈 TOTAL PRODUCTOS VENDIDOS: {t_cant}\n🎯 GRAN TOTAL COBRADO EN CAJA: {t_cob_bs:.2f} Bs\n---------------------------------------------\n📱 TOTAL EN QR          : {t_qr:.2f} Bs\n💵 TOTAL EN EFECTIVO Bs : {t_efe_bs:.2f} Bs\n💵 TOTAL EN EFECTIVO $us: {t_efe_usd:.2f} $us\n"

                    mes, anio = obtener_mes_actual()
                    r_tmp = f"Reporte_Ventas_{t_rep.replace(' ','_')}_{hoy}_{ahora}.txt"
                    with open(r_tmp, "w", encoding="utf-8") as file: file.write(txt)
                    subir_archivo_drive(r_tmp, "REPORTES", t_rep, f"REPORTES_{mes.upper()}_{anio}")
                    
                    st.text_area("Previsualización:", txt, height=300)
                    st.download_button("📥 Descargar Reporte TXT", txt, file_name=r_tmp)

            with st.expander("⚠️ Cierre de Mes"):
                if st.button("Archivar Mes Actual e Iniciar Nuevo Historial", type="secondary"):
                    mes, anio = obtener_mes_actual(); nombre = f"Historial_{mes}_{anio}"
                    try:
                        hoja_historial.duplicate(new_sheet_name=nombre)
                        hoja_historial.clear()
                        hoja_historial.append_row(["Fecha y Hora", "Tienda", "Producto", "Cantidad (Movimiento)", "Usuario (Vendedor)", "Subtotal Ref (Bs)", "Diferencia Ajuste (Bs)", "Total Ticket (Bs)", "PAGO QR (Bs)", "PAGO EFECTIVO (Bs)", "PAGO MIXTO (Total Bs)", "PAGO DOLARES ($us)"])
                        st.success(f"Mes cerrado. Se creó la pestaña '{nombre}'.")
                    except:
                        st.error("Error al archivar. (Puede que el nombre ya exista en tu Excel).")
