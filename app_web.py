import streamlit as st
import streamlit.components.v1 as components
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import pandas as pd
import os
import unicodedata
import traceback

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

# --- CONEXIÓN A GOOGLE SHEETS PARA RENDER ---
@st.cache_resource
def conectar_google_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    # 👇 AQUÍ ESTÁ EL CAMBIO: Ahora busca "credenciales.json"
    creds = ServiceAccountCredentials.from_json_keyfile_name("credenciales.json", scope)
    cliente = gspread.authorize(creds)
    archivo = cliente.open("Copia de Inventario_1") # Asegúrate de que este sea el nombre correcto de tu Excel
    return archivo
try:
    archivo = conectar_google_sheets()
    hoja_inventario = archivo.worksheet("Inventario")
    hoja_historial = archivo.worksheet("Historial")
    hoja_usuarios = archivo.worksheet("Usuarios")
except Exception as e:
    st.error("🚨 Error al conectar con Google Sheets. Detalles técnicos:")
    st.code(traceback.format_exc())
    st.stop()

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
    st.markdown("<h1 style='text-align: center;'>🛒 Acceso al Sistema POS</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            user_input = st.text_input("USUARIO")
            pass_input = st.text_input("CONTRASEÑA", type="password")
            tienda_input = st.selectbox("SUCURSAL", list(COLUMNAS_TIENDA.keys()))
            submit_btn = st.form_submit_button("ACCEDER", use_container_width=True)
            
            if submit_btn:
                usuarios_db = hoja_usuarios.get_all_records()
                encontrado = False
                for fila in usuarios_db:
                    if str(fila['Usuario']) == user_input and str(fila['Password']) == pass_input:
                        tienda_asignada = str(fila.get('Tienda', '')).strip()
                        cargo = str(fila.get('Cargo', '')).upper()
                        
                        if tienda_asignada == tienda_input or cargo == "JEFE":
                            st.session_state.usuario = user_input
                            st.session_state.cargo = cargo
                            st.session_state.tienda = tienda_input
                            st.session_state.col_index = COLUMNAS_TIENDA[tienda_input]
                            st.session_state.logged_in = True
                            encontrado = True
                            st.rerun()
                        else:
                            st.error(f"Acceso Denegado. El usuario '{user_input}' está asignado a: {tienda_asignada}")
                            encontrado = True
                            break
                if not encontrado: st.error("Usuario o contraseña incorrectos")

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
            st.success("🎉 ¡Venta registrada y descontada del inventario!")
            components.html(st.session_state.ultimo_recibo_html, height=450, scrolling=True)
            
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
                    file_name=f"Recibo_Venta_{fecha_str_descarga}.html",
                    mime="text/html",
                    use_container_width=True
                )
        else:
            col_izq, col_der = st.columns([6, 4])
            
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
                    fila_datos = hoja_inventario.row_values(f_idx)
                    
                    try:
                        stk_local = int(fila_datos[st.session_state.col_index - 1]) if len(fila_datos) >= st.session_state.col_index and fila_datos[st.session_state.col_index - 1] else 0
                    except ValueError:
                        stk_local = 0

                    s1 = fila_datos[COLUMNAS_TIENDA["MI STORE CENTER"]-1] if len(fila_datos) >= COLUMNAS_TIENDA["MI STORE CENTER"] else "0"
                    s2 = fila_datos[COLUMNAS_TIENDA["GALERIA LA PAZ"]-1] if len(fila_datos) >= COLUMNAS_TIENDA["GALERIA LA PAZ"] else "0"
                    s3 = fila_datos[COLUMNAS_TIENDA["AZTLAN"]-1] if len(fila_datos) >= COLUMNAS_TIENDA["AZTLAN"] else "0"
                    s4 = fila_datos[COLUMNAS_TIENDA["UYUSMARKET"]-1] if len(fila_datos) >= COLUMNAS_TIENDA["UYUSMARKET"] else "0"
                    
                    st.info(f"**MI STORE:** {s1} | **GALERIA LA PAZ:** {s2} | **AZTLAN:** {s3} | **UYUSMARKET:** {s4}")
                    
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

            with col_der:
                st.subheader("🛒 Carrito Actual")
                if not st.session_state.carrito:
                    st.info("El carrito está vacío.")
                else:
                    df_carrito = pd.DataFrame(st.session_state.carrito)
                    st.dataframe(df_carrito[["cantidad", "producto", "subtotal_cobrado"]].rename(columns={"cantidad":"Cant", "producto":"Prod", "subtotal_cobrado":"Bs"}), hide_index=True)
                    
                    c_b1, c_b2 = st.columns(2)
                    if c_b1.button("🗑️ Vaciar"): st.session_state.carrito = []; st.rerun()
                    if c_b2.button("↩️ Deshacer"): st.session_state.carrito.pop(); st.rerun()

                    t_ref = sum(i["subtotal_ref"] for i in st.session_state.carrito)
                    t_real = sum(i["subtotal_cobrado"] for i in st.session_state.carrito)
                    t_usd = sum(i["subtotal_usd"] for i in st.session_state.carrito)

                    st.markdown("---")
                    st.metric("TOTAL REFERENCIAL (Bs)", f"{t_ref:.2f}")
                    st.metric("TOTAL A COBRAR (Bs)", f"{t_real:.2f}")
                    st.write(f"Equivalente en Dólares: **${t_usd:.2f}**")
                    
                    if st.button("✅ FINALIZAR VENTA", type="primary", use_container_width=True):
                        fecha_h = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        filas_h = []
                        carrito_copia = list(st.session_state.carrito)
                        
                        for item in carrito_copia:
                            idx = obtener_fila_producto(datos_completos, item["producto"])
                            val_celda = hoja_inventario.cell(idx, st.session_state.col_index).value
                            s_act = int(val_celda) if val_celda else 0
                            hoja_inventario.update_cell(idx, st.session_state.col_index, s_act - item["cantidad"])
                            
                            filas_h.append([
                                fecha_h, st.session_state.tienda, item["producto"], 
                                f"-{item['cantidad']} (VENTA)", st.session_state.usuario, 
                                round(item['subtotal_ref'], 2), round(item['diferencia'], 2), round(item['subtotal_cobrado'], 2)
                            ])
                        hoja_historial.append_rows(filas_h)
                        
                        html_recibo = f"""
                        <div style="font-family:'Courier New', monospace; background:white; color:black; width:100%; max-width:350px; margin:0 auto; padding:20px; border-radius:5px; border: 1px solid #ccc;">
                            <h2 style="text-align:center; margin-bottom:5px;">{st.session_state.tienda}</h2>
                            <div style="text-align:center; font-size:12px; color:#666; margin-bottom:15px;">Fecha: {fecha_h}<br>Cajero: {st.session_state.usuario}</div>
                            <hr style="border-top:1px dashed #000;">
                            <table style="width:100%; font-size:14px; text-align:left;">
                                <tr><th>Cant</th><th>Prod</th><th style="text-align:right;">Bs</th><th style="text-align:right;">$us</th></tr>
                        """
                        for i in carrito_copia:
                            html_recibo += f"<tr><td>{i['cantidad']}</td><td>{i['producto']}</td><td style='text-align:right;'>{i['subtotal_cobrado']:.2f}</td><td style='text-align:right;'>{i['subtotal_usd']:.2f}</td></tr>"
                        html_recibo += f"""
                            </table>
                            <hr style="border-top:1px dashed #000;">
                            <table style="width:100%; font-size:16px; font-weight:bold;">
                                <tr><td>TOTAL Bs:</td><td style="text-align:right;">{t_real:.2f}</td></tr>
                                <tr><td>TOTAL $us:</td><td style="text-align:right;">{t_usd:.2f}</td></tr>
                            </table>
                            <div style="text-align:center; font-size:12px; color:#666; margin-top:20px;">¡Gracias por su compra!</div>
                        </div>
                        """
                        st.session_state.ultimo_recibo_html = html_recibo
                        st.session_state.carrito = []
                        st.session_state.datos_completos = cargar_datos_locales()
                        st.rerun()

    # ==========================================================
    # TAB 2: TRASPASOS
    # ==========================================================
    with tabs[1]:
        st.header("📦 Enviar Productos a otra Sucursal")
        prods_totales = [""] + [f[2] for f in datos_completos if len(f)>2 and f[2]]
        prod_t = st.selectbox("Selecciona el producto:", prods_totales, key="tras_prod")
        
        if prod_t:
            idx_t = obtener_fila_producto(datos_completos, prod_t)
            fila_datos = hoja_inventario.row_values(idx_t)
            try:
                stk_disp = int(fila_datos[st.session_state.col_index - 1]) if len(fila_datos) >= st.session_state.col_index and fila_datos[st.session_state.col_index - 1] else 0
            except ValueError:
                stk_disp = 0
                
            texto_stock_info = f"**SUCURSAL ACTUAL \"{st.session_state.tienda}\": {stk_disp}**"
            otras_suc = []
            
            for nombre_suc, col_suc in COLUMNAS_TIENDA.items():
                if nombre_suc != st.session_state.tienda:
                    try:
                        val_s = int(fila_datos[col_suc - 1]) if len(fila_datos) >= col_suc and fila_datos[col_suc - 1] else 0
                    except ValueError:
                        val_s = 0
                    otras_suc.append(f"{nombre_suc}={val_s}")
            
            if otras_suc:
                texto_stock_info += "  |  " + "  |  ".join(otras_suc)
                
            st.info(texto_stock_info)
            
            destinos = [s for s in COLUMNAS_TIENDA.keys() if s != st.session_state.tienda]
            t_dest = st.selectbox("Sucursal Destino:", destinos)
            t_cant = st.number_input("Cantidad a Traspasar:", 1, stk_disp if stk_disp > 0 else 1, 1)
            
            if st.button("🚚 Realizar Traspaso", type="primary"):
                if t_cant > stk_disp: st.error("No tienes suficiente stock para enviar.")
                else:
                    col_origen = st.session_state.col_index
                    col_destino = COLUMNAS_TIENDA[t_dest]
                    
                    val_orig = hoja_inventario.cell(idx_t, col_origen).value
                    s_orig_act = int(val_orig) if val_orig else 0
                    
                    val_dest = hoja_inventario.cell(idx_t, col_destino).value
                    s_dest_act = int(val_dest) if val_dest else 0
                    
                    hoja_inventario.update_cell(idx_t, col_origen, s_orig_act - t_cant)
                    hoja_inventario.update_cell(idx_t, col_destino, s_dest_act + t_cant)
                    
                    fh = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    hoja_historial.append_row([fh, st.session_state.tienda, prod_t, f"-{t_cant} (TRASPASO A {t_dest})", st.session_state.usuario, 0,0,0])
                    hoja_historial.append_row([fh, t_dest, prod_t, f"+{t_cant} (TRASPASO DE {st.session_state.tienda})", st.session_state.usuario, 0,0,0])
                    
                    st.success(f"Traspaso de {t_cant}x {prod_t} hacia {t_dest} completado.")
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
                    
                    try:
                        s_loc = int(fila_datos_aj[st.session_state.col_index - 1]) if len(fila_datos_aj) >= st.session_state.col_index and fila_datos_aj[st.session_state.col_index - 1] else 0
                    except ValueError:
                        s_loc = 0
                        
                    texto_stock_aj = f"**SUCURSAL ACTUAL \"{st.session_state.tienda}\": {s_loc}**"
                    otras_suc_aj = []
                    
                    for nombre_suc, col_suc in COLUMNAS_TIENDA.items():
                        if nombre_suc != st.session_state.tienda:
                            try:
                                val_s = int(fila_datos_aj[col_suc - 1]) if len(fila_datos_aj) >= col_suc and fila_datos_aj[col_suc - 1] else 0
                            except ValueError:
                                val_s = 0
                            otras_suc_aj.append(f"{nombre_suc}={val_s}")
                    
                    if otras_suc_aj:
                        texto_stock_aj += "  |  " + "  |  ".join(otras_suc_aj)
                        
                    st.info(texto_stock_aj)
                    
                    c_aj = st.number_input("Unidades a ajustar:", 1, value=1)
                    c_sum, c_res = st.columns(2)
                    if c_sum.button("⬆️ Agregar Stock"):
                        hoja_inventario.update_cell(idx_aj, st.session_state.col_index, s_loc + c_aj)
                        hoja_historial.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), st.session_state.tienda, p_aj, f"+{c_aj} (AGREGA STOCK)", st.session_state.usuario, 0,0,0])
                        st.success("Agregado con éxito."); st.session_state.datos_completos = cargar_datos_locales(); st.rerun()
                    if c_res.button("⬇️ Retirar Stock"):
                        hoja_inventario.update_cell(idx_aj, st.session_state.col_index, s_loc - c_aj)
                        hoja_historial.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), st.session_state.tienda, p_aj, f"-{c_aj} (STOCK CORREGIDO)", st.session_state.usuario, 0,0,0])
                        st.success("Retirado con éxito."); st.session_state.datos_completos = cargar_datos_locales(); st.rerun()

            with st.expander("📊 Reportes y Extractos Bancarios", expanded=True):
                st.subheader("Extracto Global (Todas las Tiendas)")
                if st.button("🌍 Generar Extracto Global de Hoy", type="primary"):
                    h_datos = hoja_historial.get_all_values()[1:]
                    hoy = datetime.now().strftime("%Y-%m-%d")
                    ahora = datetime.now().strftime("%H-%M-%S")
                    
                    mes, anio = obtener_mes_actual(); sub_e = f"ENTRADAS Y SALIDAS/ENTRADAS SALIDAS {mes.upper()}"
                    if not os.path.exists(sub_e): os.makedirs(sub_e, exist_ok=True)
                    
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
                    
                    components.html(html_final, height=400, scrolling=True)
                    st.download_button("📥 Descargar Extracto HTML", html_final, file_name=f"Extracto_{hoy}.html", mime="text/html")
                    st.download_button("📥 Descargar Extracto TXT", t_txt, file_name=f"Extracto_{hoy}.txt")

                st.divider()
                st.subheader("Reporte de Ventas por Sucursal")
                t_rep = st.selectbox("Consultar tienda:", list(COLUMNAS_TIENDA.keys()))
                if st.button("Generar Reporte Diario de Ventas"):
                    h_datos = hoja_historial.get_all_values()[1:]
                    hoy = datetime.now().strftime("%Y-%m-%d")
                    ahora = datetime.now().strftime("%H-%M-%S")
                    txt = f"REPORTE {t_rep} - {hoy}\n====================\n"
                    tb = 0.0; te = 0.0; tc = 0
                    
                    for f in h_datos:
                        if len(f)>7 and hoy in f[0] and f[1] == t_rep and ("(VENTA)" in f[3] or (f[3].startswith("-") and "(" not in f[3])):
                            try:
                                cant = abs(int(f[3].split()[0]))
                                b = float(f[5]); e = float(f[6]); total = float(f[7])
                                txt += f"• {f[4]} vendió {cant}x {f[2]} -> {total:.2f} Bs\n"
                                tb += b; te += e; tc += cant
                            except: pass
                            
                    txt += f"\nTOTAL PRODS: {tc}\nBASE: {tb:.2f} Bs\nEXTRAS: {te:.2f} Bs\nGRAN TOTAL EN CAJA: {(tb+te):.2f} Bs"
                    st.text_area("Previsualización:", txt, height=250)
                    st.download_button("📥 Descargar Reporte TXT", txt, f"Reporte_Ventas_{t_rep}_{hoy}_{ahora}.txt")

            with st.expander("⚠️ Cierre de Mes"):
                if st.button("Archivar Mes Actual e Iniciar Nuevo Historial", type="secondary"):
                    mes, anio = obtener_mes_actual(); nombre = f"Historial_{mes}_{anio}"
                    try:
                        hoja_historial.duplicate(new_sheet_name=nombre)
                        hoja_historial.clear()
                        hoja_historial.append_row(["Fecha y Hora", "Tienda", "Producto", "Cantidad (Movimiento)", "Usuario (Vendedor)", "Subtotal Ref (Bs)", "Diferencia Ajuste (Bs)", "Total Ticket (Bs)"])
                        st.success(f"Mes cerrado. Se creó la pestaña '{nombre}'.")
                    except:
                        st.error("Error al archivar. (Puede que el nombre ya exista en tu Excel).")
