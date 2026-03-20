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

# ==============================================================================
# CONFIGURACIÓN INICIAL DE LA PÁGINA
# ==============================================================================
st.set_page_config(page_title="POS Web - Inventario Central", page_icon="🛒", layout="wide")

# ==============================================================================
# FUNCIONES DE UTILIDAD GENERAL
# ==============================================================================
def normalizar_texto(texto):
    if not texto: return ""
    texto = str(texto)
    texto = unicodedata.normalize('NFD', texto)
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    return texto.upper().strip()

def obtener_mes_actual():
    meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    return meses[datetime.now().month - 1], datetime.now().year

# ==============================================================================
# CONFIGURACIONES GLOBALES (CONSTANTES DEL NEGOCIO)
# ==============================================================================
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

ID_CARPETA_BASE_DRIVE = "1Dm99RvDStOaWYJ5dxDgiFz9SpyzsNbwv"

# ==============================================================================
# CONEXIÓN A SERVICIOS DE GOOGLE (SHEETS Y DRIVE)
# ==============================================================================
@st.cache_resource
def conectar_servicios():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    # Se espera que el archivo credenciales.json esté en la raíz del proyecto en Render
    creds = ServiceAccountCredentials.from_json_keyfile_name("credenciales.json", scope)
    cliente = gspread.authorize(creds)
    archivo = cliente.open_by_url("https://docs.google.com/spreadsheets/d/1Mfr5GShbSnToWSSzZohsfLQe9-LX4-zvTS1MY9WflIU/edit")
    
    try:
        drive_srv = build('drive', 'v3', credentials=creds)
    except Exception as e:
        drive_srv = None
        print(f"Error al conectar con Drive API: {e}")
        
    return archivo, drive_srv

try:
    archivo, drive_service = conectar_servicios()
    hoja_inventario = archivo.worksheet("Inventario")
    hoja_historial = archivo.worksheet("Historial")
    hoja_usuarios = archivo.worksheet("Usuarios")
except Exception as e:
    st.error("🚨 Error Crítico al conectar con Google Sheets o Google Drive. Verifique sus credenciales y permisos.")
    st.code(traceback.format_exc())
    st.stop()

# ==============================================================================
# LÓGICA DE GOOGLE DRIVE (CARPETAS ANIDADAS)
# ==============================================================================
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
        print(f"Drive Error (Crear Carpeta {nombre_carpeta}): {e}")
        return None

def subir_archivo_drive(ruta_local, categoria_principal, tienda, nombre_carpeta_mes):
    if not drive_service or not ID_CARPETA_BASE_DRIVE: return
    try:
        # Nivel 1: Categoría (Ej. COMPROBANTES)
        id_categoria = crear_o_obtener_carpeta_drive(categoria_principal, ID_CARPETA_BASE_DRIVE)
        if not id_categoria: return
        
        # Nivel 2: Tienda (Ej. MI STORE CENTER). Si es global, se omite.
        id_padre_actual = id_categoria
        if tienda:
            id_tienda = crear_o_obtener_carpeta_drive(tienda, id_categoria)
            if not id_tienda: return
            id_padre_actual = id_tienda
            
        # Nivel 3: Mes y Año (Ej. COMPROBANTES_MARZO_2026)
        id_mes = crear_o_obtener_carpeta_drive(nombre_carpeta_mes, id_padre_actual)
        if not id_mes: return
            
        # Subir archivo final
        nombre_archivo = os.path.basename(ruta_local)
        file_metadata = {'name': nombre_archivo, 'parents': [id_mes]}
        mimetype = 'text/html' if ruta_local.endswith('.html') else 'text/plain'
        media = MediaFileUpload(ruta_local, mimetype=mimetype)
        
        drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    except Exception as e:
        print(f"Drive Error (Subir Archivo {ruta_local}): {e}")

# ==============================================================================
# INICIALIZACIÓN DE VARIABLES DE SESIÓN (SESSION STATE)
# ==============================================================================
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'usuario' not in st.session_state: st.session_state.usuario = ""
if 'cargo' not in st.session_state: st.session_state.cargo = ""
if 'tienda' not in st.session_state: st.session_state.tienda = ""
if 'col_index' not in st.session_state: st.session_state.col_index = 0

# Variables del Carrito y Lógica de Interfaz
if 'carrito' not in st.session_state: st.session_state.carrito = []
if 'ultimo_recibo_html' not in st.session_state: st.session_state.ultimo_recibo_html = ""
if 'modal_abierto' not in st.session_state: st.session_state.modal_abierto = None # Puede ser "pagar", "obs", "envio", "traspaso"
if 'obs_temporal' not in st.session_state: st.session_state.obs_temporal = ""

# ==============================================================================
# FUNCIONES DE CARGA Y BÚSQUEDA DE DATOS LOCALES (OPTIMIZACIÓN WEB)
# ==============================================================================
def cargar_datos_locales():
    try:
        datos_crudos = hoja_inventario.get_all_values()[1:]
        datos_comp = []
        for f in datos_crudos:
            f_ext = f + [""] * (3 - len(f)) if len(f) < 3 else f
            fila_norm = [normalizar_texto(f_ext[0]), normalizar_texto(f_ext[1]), normalizar_texto(f_ext[2])] + f_ext[3:]
            datos_comp.append(fila_norm)
        return datos_comp
    except Exception as e:
        st.error(f"Error crítico al leer datos de la hoja Inventario: {e}")
        return []

if 'datos_completos' not in st.session_state: 
    st.session_state.datos_completos = cargar_datos_locales()

def obtener_fila_producto(datos_completos, nombre_producto):
    nombre_normalizado = normalizar_texto(nombre_producto)
    for i, fila in enumerate(datos_completos):
        if len(fila) > 2 and fila[2] == nombre_normalizado:
            return i + 2 
    return -1

# ==============================================================================
# MÓDULO 1: SISTEMA DE LOGIN (CON ACCESO UNIVERSAL)
# ==============================================================================
if not st.session_state.logged_in:
    st.markdown("<h1 style='text-align: center; color: #1976D2;'>🛒 Sistema POS Web - Acceso</h1>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    
    col_vacia1, col_login, col_vacia2 = st.columns([1, 2, 1])
    with col_login:
        with st.form("form_login"):
            st.markdown("### Ingrese sus credenciales")
            user_input = st.text_input("USUARIO", help="Ingrese su usuario del sistema.")
            pass_input = st.text_input("CONTRASEÑA", type="password")
            tienda_input = st.selectbox("SELECCIONE SUCURSAL A OPERAR", list(COLUMNAS_TIENDA.keys()))
            
            st.markdown("<br>", unsafe_allow_html=True)
            submit_btn = st.form_submit_button("ACCEDER AL SISTEMA", type="primary", use_container_width=True)
            
            if submit_btn:
                if not user_input or not pass_input:
                    st.warning("Por favor, ingrese usuario y contraseña.")
                else:
                    try:
                        usuarios_db = hoja_usuarios.get_all_records()
                        encontrado = False
                        
                        for fila in usuarios_db:
                            if str(fila['Usuario']).strip() == user_input.strip() and str(fila['Password']).strip() == pass_input.strip():
                                cargo = str(fila.get('Cargo', '')).upper()
                                
                                # Aplicando la regla estricta que solicitaste: Cualquier usuario puede entrar a cualquier sucursal.
                                st.session_state.usuario = user_input.strip()
                                st.session_state.cargo = cargo
                                st.session_state.tienda = tienda_input
                                st.session_state.col_index = COLUMNAS_TIENDA[tienda_input]
                                st.session_state.logged_in = True
                                encontrado = True
                                break
                                
                        if encontrado:
                            st.rerun()
                        else:
                            st.error("❌ Usuario o contraseña incorrectos. Verifique sus datos.")
                    except Exception as e:
                        st.error(f"Error de conexión con la base de datos de usuarios: {e}")

# ==============================================================================
# MÓDULO 2: INTERFAZ PRINCIPAL DEL SISTEMA (SI EL LOGIN ES EXITOSO)
# ==============================================================================
else:
    # --------------------------------------------------------------------------
    # SIDEBAR: INFORMACIÓN DEL USUARIO Y OPCIONES GENERALES
    # --------------------------------------------------------------------------
    st.sidebar.markdown(f"## 🏬 {st.session_state.tienda}")
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"👤 **Cajero Activo:** {st.session_state.usuario}")
    st.sidebar.markdown(f"🛡️ **Rol Asignado:** {st.session_state.cargo}")
    st.sidebar.markdown("---")
    
    if st.sidebar.button("🔄 Forzar Actualización de Datos", use_container_width=True):
        with st.spinner("Sincronizando con Google Sheets..."):
            st.session_state.datos_completos = cargar_datos_locales()
        st.sidebar.success("✅ Base de datos sincronizada.")
        st.rerun()

    st.sidebar.markdown("<br><br><br>", unsafe_allow_html=True)
    if st.sidebar.button("🚪 Cerrar Sesión Segura", type="primary", use_container_width=True):
        st.session_state.clear()
        st.rerun()

    # --------------------------------------------------------------------------
    # CARGA DE VARIABLES GLOBALES EN CACHE
    # --------------------------------------------------------------------------
    datos_completos = st.session_state.datos_completos
    categorias_unicas = [""] + sorted(list(set(f[0] for f in datos_completos if f[0])))
    try: 
        valor_dolar_actual = float(hoja_inventario.cell(CELDA_DOLAR_FILA, CELDA_DOLAR_COL).value)
    except: 
        valor_dolar_actual = 10.00 # Valor por defecto seguro si falla la lectura

    # --------------------------------------------------------------------------
    # ESTRUCTURA DE PESTAÑAS (TABS)
    # --------------------------------------------------------------------------
    tab_nombres = ["🛒 Punto de Venta", "📦 Traspasos Internos"]
    if st.session_state.cargo == "JEFE": 
        tab_nombres.append("⚙️ Panel de Administrador (JEFE)")
    
    tabs = st.tabs(tab_nombres)

    # ==========================================================================
    # PESTAÑA 1: PUNTO DE VENTA (EL CORAZÓN DEL SISTEMA)
    # ==========================================================================
    with tabs[0]:
        # --- SUBRUTINA: MOSTRAR RECIBO GENERADO ---
        if st.session_state.ultimo_recibo_html != "":
            st.success("✅ Operación completada, registrada en Historial y respaldada en Google Drive.")
            st.markdown("### Documento Generado:")
            components.html(st.session_state.ultimo_recibo_html, height=550, scrolling=True)
            
            c_btn_rec1, c_btn_rec2 = st.columns(2)
            with c_btn_rec1:
                if st.button("⬅️ Realizar una Nueva Venta", type="primary", use_container_width=True):
                    st.session_state.ultimo_recibo_html = ""
                    st.session_state.modal_abierto = None
                    st.session_state.carrito = []
                    st.rerun()
            with c_btn_rec2:
                fecha_str_d = datetime.now().strftime("%Y%m%d_%H%M%S")
                st.download_button(
                    label="📥 Descargar Recibo Físico (.html)",
                    data=st.session_state.ultimo_recibo_html,
                    file_name=f"Documento_{st.session_state.tienda.replace(' ','_')}_{fecha_str_d}.html",
                    mime="text/html",
                    use_container_width=True
                )
        
        # --- SUBRUTINA: INTERFAZ NORMAL DE VENTA ---
        else:
            col_buscador, col_carrito = st.columns([5, 5])
            
            # ------------------------------------------------------------------
            # SECCIÓN IZQUIERDA: BUSCADOR Y AGREGADO AL CARRITO
            # ------------------------------------------------------------------
            with col_buscador:
                st.markdown("<h3 style='color:#1976D2;'>Buscador de Productos</h3>", unsafe_allow_html=True)
                with st.container(border=True):
                    
                    # Filtros en Cascada (Exactamente igual a Tkinter)
                    col_fcat, col_fmar = st.columns(2)
                    with col_fcat: 
                        cat_sel = st.selectbox("Filtrar por Categoría:", categorias_unicas)
                    with col_fmar: 
                        marcas_disponibles = [""] + sorted(list(set(f[1] for f in datos_completos if f[0] == cat_sel and len(f)>1))) if cat_sel else [""]
                        mar_sel = st.selectbox("Filtrar por Marca:", marcas_disponibles)
                    
                    prods_filtrados = [""] + [f[2] for f in datos_completos if (not cat_sel or f[0] == cat_sel) and (not mar_sel or f[1] == mar_sel) and len(f)>2]
                    prod_sel = st.selectbox("Seleccione el Modelo / Producto:", prods_filtrados)

                    if prod_sel:
                        f_idx = obtener_fila_producto(datos_completos, prod_sel)
                        fila_datos = datos_completos[f_idx - 2]
                        
                        # Obtener Stock Local Seguro
                        try: stk_local = int(fila_datos[st.session_state.col_index - 1]) if len(fila_datos) >= st.session_state.col_index and fila_datos[st.session_state.col_index - 1] else 0
                        except ValueError: stk_local = 0

                        # Obtener Stocks Globales (Lectura de Columnas)
                        s_msc = fila_datos[COLUMNAS_TIENDA["MI STORE CENTER"]-1] if len(fila_datos) >= COLUMNAS_TIENDA["MI STORE CENTER"] else "0"
                        s_glp = fila_datos[COLUMNAS_TIENDA["GALERIA LA PAZ"]-1] if len(fila_datos) >= COLUMNAS_TIENDA["GALERIA LA PAZ"] else "0"
                        s_azt = fila_datos[COLUMNAS_TIENDA["AZTLAN"]-1] if len(fila_datos) >= COLUMNAS_TIENDA["AZTLAN"] else "0"
                        s_uyu = fila_datos[COLUMNAS_TIENDA["UYUSMARKET"]-1] if len(fila_datos) >= COLUMNAS_TIENDA["UYUSMARKET"] else "0"
                        
                        st.info(f"📦 **MI STORE:** {s_msc} | **GALERIA:** {s_glp} | **AZTLAN:** {s_azt} | **UYUS:** {s_uyu}")
                        
                        # Lógica de Precios Matemáticos
                        precio_usd = float(fila_datos[COL_PRECIO_USD - 1]) if len(fila_datos) >= COL_PRECIO_USD and fila_datos[COL_PRECIO_USD - 1] else 0.0
                        extra_bs = float(fila_datos[COL_PRECIO_ADICIONAL - 1]) if len(fila_datos) >= COL_PRECIO_ADICIONAL and fila_datos[COL_PRECIO_ADICIONAL - 1] else 0.0
                        
                        mayor_bs = precio_usd * valor_dolar_actual
                        menor_bs = mayor_bs + extra_bs
                        
                        # Panel de Selección de Cantidad y Precio
                        st.markdown("---")
                        col_c1, col_c2, col_c3 = st.columns([1.5, 2, 2])
                        with col_c1: 
                            cant_ingresada = st.number_input("Cantidad", min_value=1, max_value=9999, value=1)
                        with col_c2: 
                            st.text_input("Precio Ref. Mayor (Bs)", f"{mayor_bs:.2f}", disabled=True)
                        with col_c3: 
                            cobro_ingresado = st.number_input("Precio de Cobro c/u (Bs)", value=float(menor_bs), format="%.2f")

                        # Botón Añadir al Carrito (Con Validación de Stock)
                        if st.button("➕ AÑADIR AL CARRITO", type="primary", use_container_width=True):
                            if cant_ingresada > stk_local:
                                st.error(f"❌ Stock insuficiente. Solo hay {stk_local} unidades disponibles en {st.session_state.tienda}.")
                            else:
                                subt_ref_calculado = cant_ingresada * (mayor_bs + extra_bs)
                                subt_cobrado_calculado = cant_ingresada * cobro_ingresado
                                
                                st.session_state.carrito.append({
                                    "producto": prod_sel, 
                                    "cantidad": cant_ingresada, 
                                    "subtotal_ref": subt_ref_calculado, 
                                    "subtotal_cobrado": subt_cobrado_calculado, 
                                    "subtotal_usd": subt_cobrado_calculado / valor_dolar_actual if valor_dolar_actual > 0 else 0.0,
                                    "diferencia": subt_cobrado_calculado - subt_ref_calculado
                                })
                                st.success(f"{cant_ingresada}x {prod_sel} añadidos al carrito.")
                                st.rerun()

                st.markdown("<br>", unsafe_allow_html=True)
                
                # --- RECUPERACIÓN DE COTIZACIONES ---
                with st.expander("📂 Importar Cotización Guardada (.html)"):
                    cot_file = st.file_uploader("Suba el archivo de la cotización:", type=["html"])
                    if cot_file is not None:
                        if st.button("🔄 Cargar Productos de la Cotización"):
                            contenido = cot_file.getvalue().decode("utf-8")
                            # Regex exactos de Tkinter para V1, V2 y V3
                            patrones = [
                                r"<tr>\s*<td>(\d+)</td>\s*<td>(.*?)</td>\s*<td class=\"right\">([\d.]+)</td>\s*<td class=\"right\">([\d.]+)</td>\s*<td class=\"right\">([\d.]+)</td>\s*<td class=\"right\">([\d.]+)</td>\s*</tr>",
                                r"<tr>\s*<td>(\d+)</td>\s*<td>(.*?)</td>\s*<td class=\"right\">([\d.]+)</td>\s*<td class=\"right\">([\d.]+)</td>\s*<td class=\"right\">([\d.]+)</td>\s*</tr>",
                                r"<tr>\s*<td>(\d+)</td>\s*<td>(.*?)</td>\s*<td class=\"right\">([\d.]+)</td>\s*<td class=\"right\">([\d.]+)</td>\s*</tr>"
                            ]
                            matches = []
                            tipo_patron = 0
                            for idx_p, patron in enumerate(patrones):
                                matches = re.findall(patron, contenido)
                                if matches:
                                    tipo_patron = 3 - idx_p
                                    break
                                    
                            if not matches:
                                st.error("No se encontraron productos válidos en el archivo HTML. Asegúrese de que es una cotización del sistema.")
                            else:
                                st.session_state.carrito = [] # Se limpia el carrito actual si se carga una cotización
                                prods_no_encontrados = []
                                
                                for match in matches:
                                    if tipo_patron == 3: cant_s, prod_n, _, _, bs_s, _ = match
                                    elif tipo_patron == 2: cant_s, prod_n, _, bs_s, _ = match
                                    else: cant_s, prod_n, bs_s, _ = match
                                    
                                    cant_int = int(cant_s); prod_nom = normalizar_texto(prod_n); subt_bs = float(bs_s)
                                    
                                    # Verificar existencia en DB
                                    f_idx = obtener_fila_producto(datos_completos, prod_nom)
                                    if f_idx == -1:
                                        prods_no_encontrados.append(prod_nom)
                                        continue
                                    
                                    f_dat = datos_completos[f_idx - 2]
                                    p_usd = float(f_dat[COL_PRECIO_USD-1]) if len(f_dat)>=COL_PRECIO_USD and f_dat[COL_PRECIO_USD-1] else 0.0
                                    e_bs = float(f_dat[COL_PRECIO_ADICIONAL-1]) if len(f_dat)>=COL_PRECIO_ADICIONAL and f_dat[COL_PRECIO_ADICIONAL-1] else 0.0
                                    
                                    subt_ref_calc = cant_int * ((p_usd * valor_dolar_actual) + e_bs)
                                    st.session_state.carrito.append({
                                        "producto": prod_nom, "cantidad": cant_int, "subtotal_ref": subt_ref_calc, 
                                        "subtotal_cobrado": subt_bs, "subtotal_usd": subt_bs / valor_dolar_actual if valor_dolar_actual > 0 else 0.0,
                                        "diferencia": subt_bs - subt_ref_calc
                                    })
                                
                                if prods_no_encontrados: 
                                    st.warning("⚠️ Los siguientes productos ya no existen en la base de datos y fueron omitidos: " + ", ".join(prods_no_encontrados))
                                else:
                                    st.success("✅ Cotización importada al carrito exitosamente.")
                                st.rerun()

            # ------------------------------------------------------------------
            # SECCIÓN DERECHA: GESTIÓN DEL CARRITO Y COBRO
            # ------------------------------------------------------------------
            with col_carrito:
                st.markdown("<h3 style='color:#388E3C;'>🛒 Carrito de Compras</h3>", unsafe_allow_html=True)
                
                if not st.session_state.carrito:
                    st.warning("El carrito está vacío. Agregue productos desde el buscador.")
                else:
                    with st.container(border=True):
                        # REPLICA DE FUNCIONALIDAD TKINTER: Lista, Edición y Borrado Individual
                        for idx, item in enumerate(st.session_state.carrito):
                            c_tit, c_inp, c_mto, c_btn = st.columns([4, 2, 2, 1])
                            
                            c_tit.markdown(f"**{item['producto']}**")
                            
                            # Logica de edición en tiempo real de cantidad
                            nueva_cant = c_inp.number_input("Cant.", min_value=1, max_value=9999, value=item['cantidad'], key=f"edit_{idx}", label_visibility="collapsed")
                            
                            if nueva_cant != item['cantidad']:
                                f_idx = obtener_fila_producto(datos_completos, item['producto'])
                                stk_act = int(datos_completos[f_idx-2][st.session_state.col_index-1]) if f_idx != -1 else 0
                                
                                if nueva_cant > stk_act:
                                    st.error(f"Stock excedido ({stk_act} máximo)")
                                else:
                                    # Recalcular precios proporcionales
                                    precio_unitario_cob = item['subtotal_cobrado'] / item['cantidad']
                                    precio_unitario_ref = item['subtotal_ref'] / item['cantidad']
                                    
                                    st.session_state.carrito[idx]['cantidad'] = nueva_cant
                                    st.session_state.carrito[idx]['subtotal_cobrado'] = precio_unitario_cob * nueva_cant
                                    st.session_state.carrito[idx]['subtotal_ref'] = precio_unitario_ref * nueva_cant
                                    st.session_state.carrito[idx]['subtotal_usd'] = (precio_unitario_cob * nueva_cant) / valor_dolar_actual if valor_dolar_actual > 0 else 0.0
                                    st.session_state.carrito[idx]['diferencia'] = st.session_state.carrito[idx]['subtotal_cobrado'] - st.session_state.carrito[idx]['subtotal_ref']
                                    st.rerun()
                                    
                            c_mto.write(f"**{item['subtotal_cobrado']:.2f} Bs**")
                            
                            # Logica de Borrado del ultimo / especifico elemento
                            if c_btn.button("🗑️", key=f"del_btn_{idx}", help="Eliminar este producto"):
                                st.session_state.carrito.pop(idx)
                                st.rerun()

                        # Sumatorias Totales
                        t_ref = sum(i["subtotal_ref"] for i in st.session_state.carrito)
                        t_real = sum(i["subtotal_cobrado"] for i in st.session_state.carrito)
                        t_usd = sum(i["subtotal_usd"] for i in st.session_state.carrito)

                        st.markdown("---")
                        col_tot1, col_tot2 = st.columns(2)
                        col_tot1.metric("SUBTOTAL REFERENCIAL (Bs)", f"{t_ref:.2f}")
                        col_tot2.metric("💳 TOTAL A COBRAR (Bs)", f"{t_real:.2f}", f"${t_usd:.2f} USD", delta_color="off")
                        
                        col_vd1, col_vd2 = st.columns(2)
                        if col_vd1.button("↩️ Deshacer Último", use_container_width=True):
                            if st.session_state.carrito: st.session_state.carrito.pop(); st.rerun()
                        if col_vd2.button("🗑️ Vaciar Todo", use_container_width=True):
                            st.session_state.carrito = []; st.rerun()

                    st.markdown("<br>", unsafe_allow_html=True)

                    # ------------------------------------------------------------------
                    # BOTONERA PRINCIPAL DE ACCIONES (SIMULA TKINTER BUTTONS)
                    # ------------------------------------------------------------------
                    # Si no hay ningún modal abierto, mostramos los botones normales
                    if st.session_state.modal_abierto is None:
                        col_acc1, col_acc2 = st.columns(2)
                        
                        if col_acc1.button("📝 GENERAR COTIZACIÓN", use_container_width=True):
                            # LOGICA DE COTIZACIÓN DIRECTA (SIN AFECTAR INVENTARIO)
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
                            
                            # Guardado y subida a Drive Automática
                            mes, anio = obtener_mes_actual()
                            t_seg = st.session_state.tienda.replace(" ", "_")
                            c_mes = f"COTIZACIONES_{mes.upper()}_{anio}"
                            ruta_tmp = f"Cotizacion_{t_seg}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
                            
                            with open(ruta_tmp, "w", encoding="utf-8") as f: f.write(html_cot)
                            subir_archivo_drive(ruta_tmp, "COTIZACIONES", st.session_state.tienda, c_mes)
                            
                            st.session_state.ultimo_recibo_html = html_cot
                            st.session_state.carrito = []
                            st.rerun()

                        if col_acc2.button("✅ FINALIZAR VENTA", type="primary", use_container_width=True):
                            st.session_state.modal_abierto = "pago_normal"
                            st.rerun()

                        if st.button("⚠️ REALIZAR VENTA CON OBSERVACIÓN", use_container_width=True):
                            st.session_state.modal_abierto = "pago_obs"
                            st.rerun()

                    # ------------------------------------------------------------------
                    # PANELES DE PAGO INTERACTIVOS (SUSTITUTO DE TOPLEVEL)
                    # ------------------------------------------------------------------
                    if st.session_state.modal_abierto in ["pago_normal", "pago_obs"]:
                        st.markdown("<hr style='border: 2px solid #FF9800;'>", unsafe_allow_html=True)
                        st.subheader("💳 Panel de Cobro")
                        st.info(f"Monto a cubrir: **{t_real:.2f} Bs**")
                        
                        if st.session_state.modal_abierto == "pago_obs":
                            st.session_state.obs_temporal = st.text_input("⚠️ Ingrese la Observación de la venta:")

                        # Botones de Pago Rápido
                        col_pr1, col_pr2 = st.columns(2)
                        btn_efectivo = col_pr1.button("💵 COBRAR 100% EFECTIVO", use_container_width=True)
                        btn_qr = col_pr2.button("📱 COBRAR 100% QR", use_container_width=True)
                        
                        # Panel de Pago Mixto
                        st.markdown("##### O seleccione Pago Mixto (Especifique montos)")
                        col_pm1, col_pm2, col_pm3 = st.columns(3)
                        with col_pm1: v_efe = st.number_input("Efectivo (Bs)", 0.0, format="%.2f")
                        with col_pm2: v_qr = st.number_input("QR (Bs)", 0.0, format="%.2f")
                        with col_pm3: v_usd = st.number_input("Dólares ($us)", 0.0, format="%.2f")
                        
                        btn_mixto = st.button("✅ Procesar Pago Mixto", type="primary", use_container_width=True)
                        if st.button("❌ Cancelar Operación", use_container_width=True):
                            st.session_state.modal_abierto = None
                            st.rerun()

                        # Lógica de procesamiento de pagos
                        procesar = False
                        txt_metodo = ""; p_efe = 0.0; p_qr = 0.0; p_usd = 0.0
                        
                        if btn_efectivo:
                            txt_metodo = "EFECTIVO"; p_efe = t_real; procesar = True
                        elif btn_qr:
                            txt_metodo = "QR"; p_qr = t_real; procesar = True
                        elif btn_mixto:
                            total_ingresado = v_efe + v_qr + (v_usd * valor_dolar_actual)
                            if round(total_ingresado, 2) < round(t_real, 2):
                                st.error(f"Falta dinero. Ingresaste {total_ingresado:.2f} Bs de los {t_real:.2f} Bs requeridos.")
                            else:
                                txt_metodo = f"MIXTO (Efe: {v_efe:.2f} Bs | QR: {v_qr:.2f} Bs | USD: {v_usd:.2f} $us)"
                                p_efe = v_efe; p_qr = v_qr; p_usd = v_usd; procesar = True
                                
                        if procesar:
                            # Validación extra para observación
                            if st.session_state.modal_abierto == "pago_obs" and not st.session_state.obs_temporal.strip():
                                st.error("Debe ingresar el texto de la observación para continuar.")
                            else:
                                with st.spinner("Procesando venta en la nube..."):
                                    fecha_h = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    filas_historial = []
                                    
                                    for item in st.session_state.carrito:
                                        idx = obtener_fila_producto(datos_completos, item["producto"])
                                        s_act = int(hoja_inventario.cell(idx, st.session_state.col_index).value or 0)
                                        # 1. Descuento de Inventario
                                        hoja_inventario.update_cell(idx, st.session_state.col_index, s_act - item["cantidad"])
                                        
                                        # 2. Cálculos para las 12 columnas exactas
                                        ratio = item['subtotal_cobrado'] / t_real if t_real > 0 else 0
                                        i_qr = round(p_qr * ratio, 2)
                                        i_efe = round(p_efe * ratio, 2)
                                        i_usd = round(p_usd * ratio, 2)
                                        i_mixto = round(i_qr + i_efe + (i_usd * valor_dolar_actual), 2)
                                        
                                        t_movimiento = f"-{item['cantidad']} (VENTA)"
                                        if st.session_state.modal_abierto == "pago_obs": t_movimiento += f" [OBS: {st.session_state.obs_temporal}]"
                                        t_movimiento += f" [PAGO: {txt_metodo}]"
                                        
                                        # 3. Creación de la Fila del Historial
                                        filas_historial.append([
                                            fecha_h, 
                                            st.session_state.tienda, 
                                            item["producto"], 
                                            t_movimiento, 
                                            st.session_state.usuario,
                                            round(item['subtotal_ref'], 2), 
                                            round(item['diferencia'], 2), 
                                            round(item['subtotal_cobrado'], 2),
                                            i_qr, 
                                            i_efe, 
                                            i_mixto, 
                                            i_usd
                                        ])
                                        
                                    hoja_historial.append_rows(filas_historial)
                                    
                                    # 4. Creación del HTML del Comprobante
                                    html_venta = f"""
                                    <div style="font-family:'Courier New', monospace; background:white; color:black; width:100%; max-width:400px; margin:0 auto; padding:20px; border-radius:5px; border: 1px solid #ccc;">
                                        <h2 style="text-align:center;">{st.session_state.tienda}</h2>
                                        <div style="text-align:center; font-size:12px; color:#666;">COMPROBANTE DE VENTA<br>Fecha: {fecha_h}<br>Cajero: {st.session_state.usuario}<br>Método: <strong>{txt_metodo}</strong></div>
                                        <hr style="border-top:1px dashed #999;">
                                        <table style="width:100%; font-size:13px; border-collapse:collapse;">
                                            <tr style="background:#f0f0f0; border-bottom:2px solid #555;"><th>Cant</th><th>Producto</th><th style="text-align:right;">P.Unit Bs</th><th style="text-align:right;">P.Unit $us</th><th style="text-align:right;">Subt. Bs</th><th style="text-align:right;">Subt. $us</th></tr>
                                    """
                                    for i in st.session_state.carrito:
                                        pu_b = i['subtotal_cobrado'] / i['cantidad'] if i['cantidad']>0 else 0
                                        pu_u = i['subtotal_usd'] / i['cantidad'] if i['cantidad']>0 else 0
                                        html_venta += f"<tr><td style='text-align:center; border:1px solid #aaa;'>{i['cantidad']}</td><td style='border:1px solid #aaa;'>{i['producto']}</td><td style='text-align:right; border:1px solid #aaa;'>{pu_b:.2f}</td><td style='text-align:right; border:1px solid #aaa;'>{pu_u:.2f}</td><td style='text-align:right; border:1px solid #aaa;'>{i['subtotal_cobrado']:.2f}</td><td style='text-align:right; border:1px solid #aaa;'>{i['subtotal_usd']:.2f}</td></tr>"
                                    html_venta += f"""
                                        </table><hr style="border-top:1px dashed #999;">
                                        <table style="width:100%; font-size:16px; font-weight:bold;">
                                            <tr><td>TOTAL Bs:</td><td style="text-align:right;">{t_real:.2f}</td></tr>
                                            <tr><td>TOTAL $us:</td><td style="text-align:right;">{t_usd:.2f}</td></tr>
                                        </table>
                                        <div style="text-align:center; font-size:12px; color:#666; margin-top:15px;">Teléfonos de referencia: 75295017 - 78851301<br>¡Gracias por su preferencia!<br>Vuelva pronto.</div>
                                    </div>
                                    """
                                    
                                    # 5. Guardar en Drive
                                    mes, anio = obtener_mes_actual()
                                    t_segura = st.session_state.tienda.replace(" ", "_")
                                    c_mes = f"COMPROBANTES_{mes.upper()}_{anio}"
                                    ruta_tmp = f"Factura_{t_segura}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
                                    with open(ruta_tmp, "w", encoding="utf-8") as f: f.write(html_venta)
                                    subir_archivo_drive(ruta_tmp, "COMPROBANTES", st.session_state.tienda, c_mes)

                                    # 6. Reset y Mostrar Factura
                                    st.session_state.ultimo_recibo_html = html_venta
                                    st.session_state.carrito = []
                                    st.session_state.modal_abierto = None
                                    st.session_state.datos_completos = cargar_datos_locales()
                                    st.rerun()

    # ==========================================================================
    # PESTAÑA 2: TRASPASOS Y ENVÍOS
    # ==========================================================================
    with tabs[1]:
        st.header("📦 Traspasar o Enviar Productos")
        prods_totales = [""] + [f[2] for f in datos_completos if len(f)>2 and f[2]]
        prod_t = st.selectbox("Selecciona el producto a traspasar:", prods_totales, key="t_prod")
        
        if prod_t:
            idx_t = obtener_fila_producto(datos_completos, prod_t)
            fila_datos_t = datos_completos[idx_t - 2]
            
            try: stk_disp_t = int(fila_datos_t[st.session_state.col_index - 1]) if len(fila_datos_t) >= st.session_state.col_index and fila_datos_t[st.session_state.col_index - 1] else 0
            except ValueError: stk_disp_t = 0
                
            texto_inf = f"**STOCK EN \"{st.session_state.tienda}\": {stk_disp_t}**"
            osuc = []
            for ns, cs in COLUMNAS_TIENDA.items():
                if ns != st.session_state.tienda:
                    try: v_s = int(fila_datos_t[cs - 1]) if len(fila_datos_t) >= cs and fila_datos_t[cs - 1] else 0
                    except ValueError: v_s = 0
                    osuc.append(f"{ns}={v_s}")
            
            if osuc: texto_inf += "  |  " + "  |  ".join(osuc)
            st.info(texto_inf)
            
            st.markdown("#### Detalles del Envío")
            destinos = [s for s in COLUMNAS_TIENDA.keys() if s != st.session_state.tienda] + ["Beni", "Sucre", "Cochabamba", "Oruro", "Pando", "Potosí", "Santa Cruz de la Sierra", "Tarija"]
            t_dest = st.selectbox("Destino (Sucursal o Departamento Exterior):", destinos)
            t_cant = st.number_input("Cantidad a enviar:", 1, stk_disp_t if stk_disp_t > 0 else 1, 1)
            
            if st.button("🚚 Confirmar Envío", type="primary", use_container_width=True):
                if t_cant > stk_disp_t: 
                    st.error("No tienes suficiente stock para realizar este envío.")
                else:
                    with st.spinner("Registrando envío..."):
                        col_orig = st.session_state.col_index
                        val_orig = hoja_inventario.cell(idx_t, col_orig).value
                        hoja_inventario.update_cell(idx_t, col_orig, (int(val_orig) if val_orig else 0) - t_cant)
                        
                        fh = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        if t_dest in COLUMNAS_TIENDA:
                            # Es Traspaso Interno a otra sucursal
                            col_des = COLUMNAS_TIENDA[t_dest]
                            val_des = hoja_inventario.cell(idx_t, col_des).value
                            hoja_inventario.update_cell(idx_t, col_des, (int(val_des) if val_des else 0) + t_cant)
                            
                            hoja_historial.append_row([fh, st.session_state.tienda, prod_t, f"-{t_cant} (TRASPASO A {t_dest})", st.session_state.usuario, 0,0,0,0,0,0,0])
                            hoja_historial.append_row([fh, t_dest, prod_t, f"+{t_cant} (TRASPASO DE {st.session_state.tienda})", st.session_state.usuario, 0,0,0,0,0,0,0])
                            st.success(f"✅ Traspaso interno de {t_cant} unidades hacia {t_dest} completado.")
                        else:
                            # Es Envío a Departamento Externo
                            hoja_historial.append_row([fh, st.session_state.tienda, prod_t, f"-{t_cant} (ENVIO A {t_dest.upper()})", st.session_state.usuario, 0,0,0,0,0,0,0])
                            st.success(f"✅ Envío externo de {t_cant} unidades hacia {t_dest} registrado.")
                            
                        st.session_state.datos_completos = cargar_datos_locales()

    # ==========================================================================
    # PESTAÑA 3: PANEL DE ADMINISTRADOR (JEFE ONLY)
    # ==========================================================================
    if st.session_state.cargo == "JEFE":
        with tabs[2]:
            st.header("⚙️ Panel de Control Global - Administrador")
            
            # --- 1. CONFIGURACIÓN DÓLAR Y PRECIOS ---
            with st.expander("💰 1. Modificar Precios y Dólar Base", expanded=False):
                cd1, cd2 = st.columns(2)
                with cd1:
                    st.markdown("#### Tipo de Cambio")
                    n_dol = st.number_input("Cotización Dólar (Bs/USD)", value=float(valor_dolar_actual))
                    if st.button("Actualizar Dólar en todo el Sistema", use_container_width=True):
                        hoja_inventario.update_cell(CELDA_DOLAR_FILA, CELDA_DOLAR_COL, n_dol)
                        st.success("✅ Dólar actualizado."); st.rerun()
                        
                with cd2:
                    st.markdown("#### Configurar Precios por Producto")
                    p_conf = st.selectbox("Elegir Producto:", [""] + [f[2] for f in datos_completos if len(f)>2], key="cp")
                    if p_conf:
                        idx_c = obtener_fila_producto(datos_completos, p_conf)
                        fila_c = hoja_inventario.row_values(idx_c)
                        v_usd = float(fila_c[COL_PRECIO_USD-1]) if len(fila_c)>=COL_PRECIO_USD and fila_c[COL_PRECIO_USD-1] else 0.0
                        v_ext = float(fila_c[COL_PRECIO_ADICIONAL-1]) if len(fila_c)>=COL_PRECIO_ADICIONAL and fila_c[COL_PRECIO_ADICIONAL-1] else 0.0
                        
                        n_usd = st.number_input("Precio USD Base (Mayor) $:", value=v_usd)
                        n_ext = st.number_input("Extra de Ganancia (Menor) Bs:", value=v_ext)
                        if st.button("Guardar Nuevos Precios", type="primary", use_container_width=True):
                            hoja_inventario.update_cell(idx_c, COL_PRECIO_USD, n_usd)
                            hoja_inventario.update_cell(idx_c, COL_PRECIO_ADICIONAL, n_ext)
                            st.success(f"✅ Precios guardados para {p_conf}.")
                            st.session_state.datos_completos = cargar_datos_locales()
                            st.rerun()

            # --- 2. AJUSTES DIRECTOS (AUMENTAR/RETIRAR) ---
            with st.expander("📦 2. Ajuste Directo y Rápido de Stock", expanded=False):
                p_aj = st.selectbox("Seleccione el producto a ajustar:", [""] + [f[2] for f in datos_completos if len(f)>2], key="ap")
                if p_aj:
                    idx_aj = obtener_fila_producto(datos_completos, p_aj)
                    fila_datos_aj = hoja_inventario.row_values(idx_aj)
                    
                    suc_aj = st.selectbox("¿En qué sucursal afectará el stock?", list(COLUMNAS_TIENDA.keys()))
                    col_aj = COLUMNAS_TIENDA[suc_aj]
                    
                    try: s_loc_aj = int(fila_datos_aj[col_aj - 1]) if len(fila_datos_aj) >= col_aj and fila_datos_aj[col_aj - 1] else 0
                    except ValueError: s_loc_aj = 0
                        
                    st.info(f"El stock actual de {p_aj} en **{suc_aj}** es de **{s_loc_aj} unidades**.")
                    
                    cant_aj = st.number_input("¿Cuántas unidades se ajustarán?", 1, value=1)
                    
                    cj1, cj2 = st.columns(2)
                    if cj1.button("⬆️ AUMENTAR (Suma)", type="primary", use_container_width=True):
                        hoja_inventario.update_cell(idx_aj, col_aj, s_loc_aj + cant_aj)
                        hoja_historial.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), suc_aj, p_aj, f"+{cant_aj} (AGREGA STOCK)", st.session_state.usuario, 0,0,0,0,0,0,0])
                        st.success("✅ Stock aumentado."); st.session_state.datos_completos = cargar_datos_locales(); st.rerun()
                    
                    if cj2.button("⬇️ RETIRAR (Resta)", use_container_width=True):
                        if s_loc_aj - cant_aj < 0: 
                            st.error("No se puede retirar esa cantidad (el stock quedaría en negativo).")
                        else:
                            hoja_inventario.update_cell(idx_aj, col_aj, s_loc_aj - cant_aj)
                            hoja_historial.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), suc_aj, p_aj, f"-{cant_aj} (STOCK CORREGIDO)", st.session_state.usuario, 0,0,0,0,0,0,0])
                            st.success("✅ Stock retirado."); st.session_state.datos_completos = cargar_datos_locales(); st.rerun()

            # --- 3. REPORTES Y EXTRACTOS ---
            with st.expander("📊 3. Generación de Reportes y Extractos", expanded=False):
                st.markdown("#### A. Extracto Global (Diario)")
                st.caption("Muestra absolutamente todos los movimientos de entradas, salidas y traspasos de todas las tiendas de HOY.")
                if st.button("🌍 Generar Extracto Global", use_container_width=True):
                    with st.spinner("Recopilando datos de todas las sucursales..."):
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

                st.markdown("---")
                st.markdown("#### B. Reporte Diario de Ventas Específico")
                st.caption("Analiza las ventas en firme y la recaudación de caja de una sola tienda elegida.")
                t_rep_venta = st.selectbox("Seleccione la tienda a evaluar:", list(COLUMNAS_TIENDA.keys()))
                
                if st.button("📊 Generar Reporte de Caja", type="primary", use_container_width=True):
                    with st.spinner(f"Analizando ventas de {t_rep_venta}..."):
                        h_datos = hoja_historial.get_all_values()[1:]
                        hoy = datetime.now().strftime("%Y-%m-%d")
                        ahora = datetime.now().strftime("%H-%M-%S")
                        
                        r_detallado = {}; t_cant = 0; t_cob_bs = 0.0; t_qr = 0.0; t_efe_bs = 0.0; t_efe_usd = 0.0
                        
                        for f in h_datos:
                            if len(f)<5: continue
                            if hoy in f[0] and f[1] == t_rep_venta and ("(VENTA)" in f[3] or (f[3].startswith("-") and "(" not in f[3])):
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

                        txt = f"📊 INFORME DETALLADO DE VENTAS - {hoy} {ahora}\nSucursal: {t_rep_venta}\nGenerado por: {st.session_state.usuario}\n{'='*45}\n\n"
                        if not r_detallado: txt += "No hay ventas registradas hoy en esta sucursal."
                        else:
                            for v, dat in r_detallado.items():
                                txt += f"👤 VENDEDOR: {v}\n"
                                for p, inf in dat['prods'].items():
                                    txt += f"  • {p}: {inf['cant']} u. -> {inf['bs']:.2f} Bs\n"
                                txt += f"  ----------------------\n  💰 TOTAL COBRADO : {dat['t_cobrado']:.2f} Bs\n{'='*45}\n"
                            txt += f"\n📈 TOTAL PRODUCTOS VENDIDOS: {t_cant}\n🎯 GRAN TOTAL COBRADO EN CAJA: {t_cob_bs:.2f} Bs\n---------------------------------------------\n📱 TOTAL EN QR          : {t_qr:.2f} Bs\n💵 TOTAL EN EFECTIVO Bs : {t_efe_bs:.2f} Bs\n💵 TOTAL EN EFECTIVO $us: {t_efe_usd:.2f} $us\n"

                        mes, anio = obtener_mes_actual()
                        r_tmp = f"Reporte_Ventas_{t_rep_venta.replace(' ','_')}_{hoy}_{ahora}.txt"
                        with open(r_tmp, "w", encoding="utf-8") as file: file.write(txt)
                        subir_archivo_drive(r_tmp, "REPORTES", t_rep_venta, f"REPORTES_{mes.upper()}_{anio}")
                        
                        st.text_area("📄 Previsualización del Reporte:", txt, height=300)
                        st.download_button("📥 Descargar Reporte TXT", txt, file_name=r_tmp)

            # --- 4. CIERRE DE MES (MANTENIMIENTO) ---
            with st.expander("🛑 4. Zona de Peligro (Limpieza y Cierre)", expanded=False):
                st.warning("⚠️ **Atención:** Archivar el mes cortará el historial actual y lo dejará en blanco, guardando la copia en una pestaña nueva del Excel.")
                if st.button("Archivar Mes Actual e Iniciar Nuevo Historial", type="secondary", use_container_width=True):
                    mes, anio = obtener_mes_actual(); nombre = f"Historial_{mes}_{anio}"
                    try:
                        hoja_historial.duplicate(new_sheet_name=nombre)
                        hoja_historial.clear()
                        hoja_historial.append_row(["Fecha y Hora", "Tienda", "Producto", "Cantidad (Movimiento)", "Usuario (Vendedor)", "Subtotal Ref (Bs)", "Diferencia Ajuste (Bs)", "Total Ticket (Bs)", "PAGO QR (Bs)", "PAGO EFECTIVO (Bs)", "PAGO MIXTO (Total Bs)", "PAGO DOLARES ($us)"])
                        st.success(f"✅ Mes archivado con éxito. Se creó la pestaña de seguridad '{nombre}'.")
                    except Exception as e:
                        st.error(f"Error al archivar. Es posible que ya exista una pestaña llamada '{nombre}' en su Excel. Revise Google Sheets.")
