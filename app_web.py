import tkinter as tk
from tkinter import ttk, messagebox
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import os
import sys
import webbrowser
import unicodedata  

# --- FUNCIÓN PARA ENCONTRAR ARCHIVOS OCULTOS EN EL .EXE ---
def obtener_ruta_recurso(ruta_relativa):
    try:
        ruta_base = sys._MEIPASS
    except Exception:
        ruta_base = os.path.abspath(".")
    return os.path.join(ruta_base, ruta_relativa)

# --- FUNCIÓN PARA NORMALIZAR TEXTO (MAYÚSCULAS Y SIN ACENTOS) ---
def normalizar_texto(texto):
    if not texto: return ""
    texto = str(texto)
    texto = unicodedata.normalize('NFD', texto)
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    return texto.upper().strip()

# --- CONFIGURACIÓN DE LA SUCURSAL (DINÁMICA) ---
NOMBRE_TIENDA = ""
COLUMNAS_TIENDA = {
    "MI STORE CENTER": 4,  
    "GALERIA LA PAZ": 5,       
    "AZTLAN": 6,       
    "UYUSMARKET": 7        
}
COL_INDEX = 0

# --- CONFIGURACIÓN DE CELDAS EN GOOGLE SHEETS ---
CELDA_DOLAR_FILA = 2
CELDA_DOLAR_COL = 9        
COL_PRECIO_USD = 10        
COL_PRECIO_ADICIONAL = 11  

# --- 1. CONEXIÓN A LA NUBE ---
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
ruta_credenciales = obtener_ruta_recurso("credenciales.json")
creds = ServiceAccountCredentials.from_json_keyfile_name(ruta_credenciales, scope)

cliente = gspread.authorize(creds)

archivo = cliente.open("Inventario_Central")
hoja_inventario = archivo.worksheet("Inventario")
hoja_historial = archivo.worksheet("Historial")
hoja_usuarios = archivo.worksheet("Usuarios")

# Variables globales para los filtros y mapeo de filas
datos_completos = []
categorias_unicas = []
lista_productos = []

def cargar_datos_locales():
    global datos_completos, categorias_unicas, lista_productos
    try:
        datos_crudos = hoja_inventario.get_all_values()[1:]
        datos_completos = []
        for f in datos_crudos:
            f_ext = f + [""] * (3 - len(f)) if len(f) < 3 else f
            fila_norm = [normalizar_texto(f_ext[0]), normalizar_texto(f_ext[1]), normalizar_texto(f_ext[2])] + f_ext[3:]
            datos_completos.append(fila_norm)
            
        categorias_unicas = sorted(list(set(f[0] for f in datos_completos if f[0])))
        lista_productos = [f[2] for f in datos_completos if len(f)>2 and f[2]]
    except Exception as e:
        print(f"Error cargando datos: {e}")

cargar_datos_locales()

def obtener_fila_producto(nombre_producto):
    nombre_normalizado = normalizar_texto(nombre_producto)
    for i, fila in enumerate(datos_completos):
        if len(fila) > 2 and fila[2] == nombre_normalizado:
            return i + 2 
    return -1

carrito = []
usuario_actual = ""
cargo_actual = ""
actualizando_precios = False

# --- FUNCIÓN DE REFRESCAR DATOS ---
def refrescar_datos_nube():
    global lista_productos, datos_completos, categorias_unicas
    try:
        cargar_datos_locales()
        
        combo_categoria['values'] = categorias_unicas
        combo_marca.set('')
        combo_productos.set('')
        combo_productos['values'] = lista_productos
       
        valor_nube = hoja_inventario.cell(CELDA_DOLAR_FILA, CELDA_DOLAR_COL).value
        if valor_nube:
            valor_dolar_var.set(str(valor_nube))
       
        messagebox.showinfo("Sincronizado", "Inventario, Precios y Dólar actualizados correctamente.")
    except Exception as e:
        messagebox.showerror("Error", f"No se pudo sincronizar: {e}")

# --- EVENTOS DE FILTROS EN CASCADA ---
def al_seleccionar_categoria(event):
    cat = normalizar_texto(combo_categoria.get())
    marcas = sorted(list(set(f[1] for f in datos_completos if f[0] == cat and len(f)>1)))
    combo_marca['values'] = marcas
    combo_marca.set('')
    combo_productos.set('')
    
    prods = [f[2] for f in datos_completos if f[0] == cat and len(f)>2]
    combo_productos['values'] = prods

def al_seleccionar_marca(event):
    cat = normalizar_texto(combo_categoria.get())
    marca = normalizar_texto(combo_marca.get())
    prods = [f[2] for f in datos_completos if f[0] == cat and f[1] == marca and len(f)>2]
    combo_productos['values'] = prods
    combo_productos.set('')

# --- FUNCIÓN AUXILIAR PARA OBTENER EL MES Y AÑO ---
def obtener_mes_actual():
    meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
             "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    mes = meses[datetime.now().month - 1]
    anio = datetime.now().year
    return mes, anio

# --- 2. FUNCIONES DE LOGIN Y VALIDACIÓN ---
def validar_login():
    global usuario_actual, cargo_actual, NOMBRE_TIENDA, COL_INDEX
   
    user = entry_user.get()
    pw = entry_pw.get()
    sucursal_seleccionada = combo_sucursal.get()
   
    try:
        usuarios_db = hoja_usuarios.get_all_records()
        encontrado = False
       
        for fila in usuarios_db:
            if str(fila['Usuario']) == user and str(fila['Password']) == pw:
                cargo = str(fila.get('Cargo', '')).upper()
                
                usuario_actual = user
                cargo_actual = cargo
                NOMBRE_TIENDA = sucursal_seleccionada
                COL_INDEX = COLUMNAS_TIENDA[NOMBRE_TIENDA]
                encontrado = True
                break
                    
        if encontrado:
            ventana_login.destroy()
            abrir_sistema_principal()
        else:
            messagebox.showerror("Error", "Usuario o contraseña incorrectos")
           
    except Exception as e:
        messagebox.showerror("Error", f"No se pudo conectar a la base de datos:\n{e}")

# --- 3. FUNCIONES DE GESTIÓN ---
def actualizar_dolar():
    global valor_dolar_var
    try:
        nuevo_valor_bs = float(valor_dolar_var.get())
        if nuevo_valor_bs <= 0:
            messagebox.showwarning("Advertencia", "El valor debe ser mayor a 0.")
            return
       
        hoja_inventario.update_cell(CELDA_DOLAR_FILA, CELDA_DOLAR_COL, nuevo_valor_bs)
        messagebox.showinfo("Éxito", f"Valor del dólar actualizado a {nuevo_valor_bs} Bs en la base de datos.")
        actualizar_precio_bs()
       
    except ValueError:
        messagebox.showerror("Error", "Ingresa un número válido (ej: 10 o 10.50).")
    except Exception as e:
        messagebox.showerror("Error", f"Error al guardar en la nube: {e}")

def guardar_precios_nube():
    producto = combo_productos.get()
    if normalizar_texto(producto) not in lista_productos:
        messagebox.showwarning("Aviso", "Selecciona un producto válido primero.")
        return
    try:
        nuevo_precio_usd = float(precio_usd_var.get())
        nuevo_adicional = float(adicional_var.get())
        if nuevo_precio_usd < 0 or nuevo_adicional < 0:
            messagebox.showerror("Error", "Los valores no pueden ser negativos.")
            return
       
        fila_idx = obtener_fila_producto(producto)
        if fila_idx == -1: return
        
        hoja_inventario.update_cell(fila_idx, COL_PRECIO_USD, nuevo_precio_usd)
        hoja_inventario.update_cell(fila_idx, COL_PRECIO_ADICIONAL, nuevo_adicional)
        messagebox.showinfo("Éxito", f"Precios base y extra guardados para {producto}.")
    except ValueError:
        messagebox.showerror("Error", "Ingresa valores numéricos válidos.")
    except Exception as e:
        messagebox.showerror("Error", f"Error de conexión: {e}")

def archivar_historial_mes():
    mes, anio = obtener_mes_actual()
    nombre_archivo = f"Historial_{mes}_{anio}"
   
    msg = f"Se creará una copia en Google Sheets llamada '{nombre_archivo}' y se limpiará el historial principal.\n\n¿Estás seguro de que deseas cerrar el mes?"
    if not messagebox.askyesno("Archivar Mes", msg):
        return
       
    try:
        hoja_historial.duplicate(new_sheet_name=nombre_archivo)
        hoja_historial.clear()
        hoja_historial.append_row(["Fecha y Hora", "Tienda", "Producto", "Cantidad (Movimiento)", "Usuario (Vendedor)", "Subtotal Ref (Bs)", "Diferencia Ajuste (Bs)", "Total Ticket (Bs)"])
        messagebox.showinfo("Éxito", f"Mes cerrado correctamente.\n\nSe guardó la copia '{nombre_archivo}' en tu Google Sheets.")
    except Exception as e:
        messagebox.showerror("Error", f"No se pudo archivar el mes. (Tal vez ya existe una pestaña con ese nombre): {e}")

def limpiar_historial():
    if not messagebox.askyesno("PELIGRO", "Vas a ELIMINAR todo el historial actual sin hacer ninguna copia.\n\n¿Estás completamente seguro de continuar?"):
        return
    try:
        hoja_historial.clear()
        hoja_historial.append_row(["Fecha y Hora", "Tienda", "Producto", "Cantidad (Movimiento)", "Usuario (Vendedor)", "Subtotal Ref (Bs)", "Diferencia Ajuste (Bs)", "Total Ticket (Bs)"])
        messagebox.showinfo("Éxito", "El historial ha sido eliminado por completo.")
    except Exception as e:
        messagebox.showerror("Error", f"No se pudo limpiar el historial: {e}")

def generar_reporte_diario(tienda_objetivo):
    try:
        mes, anio = obtener_mes_actual()
        carpeta_base = "Reportes"
        subcarpeta = os.path.join(carpeta_base, f"Reportes_{mes}_{anio}")
        if not os.path.exists(subcarpeta):
            os.makedirs(subcarpeta)

        hoy = datetime.now().strftime("%Y-%m-%d")
        ahora = datetime.now().strftime("%H-%M-%S")
        datos_historial = hoja_historial.get_all_values()[1:]
        reporte_detallado = {}
        total_dia_cantidad = 0
        total_dia_bs = 0.0
        total_extras = 0.0
       
        for fila in datos_historial:
            if len(fila) < 5: continue
            
            fecha = fila[0]
            tienda = fila[1]
            producto = fila[2]
            cantidad_str = fila[3]
            vendedor = fila[4]
           
            subtotal_bs = 0.0
            diferencia_bs = 0.0
            if len(fila) > 5 and fila[5]:
                try: subtotal_bs = float(fila[5])
                except ValueError: pass
            if len(fila) > 6 and fila[6]:
                try: diferencia_bs = float(fila[6])
                except ValueError: pass
           
            es_venta = "(VENTA)" in cantidad_str or (cantidad_str.startswith("-") and "(" not in cantidad_str)

            if hoy in fecha and tienda == tienda_objetivo and es_venta:
                try: 
                    num_str = cantidad_str.split()[0]
                    cant = abs(int(num_str))
                except ValueError: continue
                   
                if vendedor not in reporte_detallado:
                    reporte_detallado[vendedor] = {'total_base': 0.0, 'total_extra': 0.0, 'productos': {}}
                   
                if producto not in reporte_detallado[vendedor]['productos']:
                    reporte_detallado[vendedor]['productos'][producto] = {'cant': 0, 'bs': 0.0}
                   
                reporte_detallado[vendedor]['productos'][producto]['cant'] += cant
                reporte_detallado[vendedor]['productos'][producto]['bs'] += subtotal_bs
               
                reporte_detallado[vendedor]['total_base'] += subtotal_bs
                reporte_detallado[vendedor]['total_extra'] += diferencia_bs
               
                total_dia_cantidad += cant
                total_dia_bs += subtotal_bs
                total_extras += diferencia_bs

        texto_reporte = f"📊 INFORME DETALLADO DE VENTAS - {hoy} {ahora}\nSucursal: {tienda_objetivo}\nGenerado por: {usuario_actual}\n" + "="*45 + "\n\n"
       
        if not reporte_detallado:
            texto_reporte += f"No se registraron ventas hoy en {tienda_objetivo}."
        else:
            for vendedor, datos in reporte_detallado.items():
                texto_reporte += f"👤 VENDEDOR: {vendedor}\n"
                for prod, info in datos['productos'].items():
                    texto_reporte += f"  • {prod}: {info['cant']} u. -> {info['bs']:.2f} Bs (Ref)\n"
               
                dinero_total_vendedor = datos['total_base'] + datos['total_extra']
                texto_reporte += f"  ----------------------\n"
                texto_reporte += f"  Subtotal Referencial : {datos['total_base']:.2f} Bs\n"
                texto_reporte += f"  Ajustes/Extras       : {datos['total_extra']:.2f} Bs\n"
                texto_reporte += f"  💰 TOTAL GENERADO    : {dinero_total_vendedor:.2f} Bs\n"
                texto_reporte += "="*45 + "\n"
           
            gran_total_caja = total_dia_bs + total_extras
            texto_reporte += f"\n📈 TOTAL PRODUCTOS VENDIDOS: {total_dia_cantidad}\n"
            texto_reporte += f"💵 TOTAL BASE: {total_dia_bs:.2f} Bs\n"
            texto_reporte += f"💸 EXTRAS COBRADOS: {total_extras:.2f} Bs\n"
            texto_reporte += f"🎯 GRAN TOTAL EN CAJA: {gran_total_caja:.2f} Bs"
           
        nombre_archivo = f"Reporte_{tienda_objetivo.replace(' ', '_')}_{hoy}_{ahora}.txt"
        ruta_completa = os.path.abspath(os.path.join(subcarpeta, nombre_archivo))
       
        with open(ruta_completa, "w", encoding="utf-8") as f:
            f.write(texto_reporte)
           
        top = tk.Toplevel()
        top.title(f"Reporte Guardado: {ruta_completa}")
        txt = tk.Text(top, wrap="word", width=65, height=25, font=("Courier New", 10))
        txt.insert("1.0", texto_reporte)
        txt.config(state="disabled")
        txt.pack(padx=15, pady=15)
    except Exception as e:
        messagebox.showerror("Error", f"No se pudo generar el reporte: {e}")

def generar_reporte_global_movimientos():
    try:
        mes, anio = obtener_mes_actual()
        carpeta_base = "ENTRADAS Y SALIDAS"
        subcarpeta = os.path.join(carpeta_base, f"ENTRADAS SALIDAS {mes.upper()}")
        
        if not os.path.exists(subcarpeta):
            os.makedirs(subcarpeta)

        hoy = datetime.now().strftime("%Y-%m-%d")
        ahora_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ahora_arch = datetime.now().strftime("%H-%M-%S")
        
        datos_historial = hoja_historial.get_all_values()[1:]
        
        filas_html = ""
        texto_txt = f"📦 EXTRACTO DE MOVIMIENTOS GLOBALES - {hoy}\nGenerado por: {usuario_actual}\n" + "="*80 + "\n"
        texto_txt += f"{'FECHA Y HORA':<20} | {'TIENDA':<18} | {'PRODUCTO':<25} | {'CANTIDAD':<25} | {'USUARIO'}\n"
        texto_txt += "="*80 + "\n"

        reporte_mov = {s: {"Entradas": [], "Salidas": [], "Ventas": []} for s in COLUMNAS_TIENDA.keys()}

        for fila in datos_historial:
            if len(fila) < 5: continue
            fecha = fila[0]
            tienda = fila[1]
            producto = fila[2]
            movimiento = fila[3]
            usuario = fila[4]
            
            if hoy in fecha:
                clase_css = ""
                if movimiento.startswith("+"):
                    clase_css = "positivo"
                elif movimiento.startswith("-"):
                    clase_css = "negativo"
                    
                filas_html += f"""
                <tr>
                    <td>{fecha}</td>
                    <td>{tienda}</td>
                    <td>{producto}</td>
                    <td class="{clase_css}">{movimiento}</td>
                    <td>{usuario}</td>
                </tr>
                """
                
                if tienda in reporte_mov:
                    if "(TRASPASO DE" in movimiento or "(AGREGA STOCK)" in movimiento or (movimiento.startswith("+") and "(AJUSTE)" in movimiento):
                        reporte_mov[tienda]["Entradas"].append(f"{producto}: {movimiento} por {usuario}")
                    elif "(TRASPASO A" in movimiento or "(STOCK CORREGIDO)" in movimiento or (movimiento.startswith("-") and "(AJUSTE)" in movimiento):
                        reporte_mov[tienda]["Salidas"].append(f"{producto}: {movimiento} por {usuario}")
                    elif "(VENTA)" in movimiento or (movimiento.startswith("-") and "(" not in movimiento):
                        reporte_mov[tienda]["Ventas"].append(f"{producto}: {movimiento} por {usuario}")

        if not filas_html:
            filas_html = "<tr><td colspan='5' style='text-align:center; padding: 20px;'>No hay movimientos registrados en el día de hoy.</td></tr>"

        html_content = f"""
        <!DOCTYPE html>
        <html lang="es">
        <head>
            <meta charset="UTF-8">
            <title>Extracto Bancario de Inventario</title>
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #eef2f3; padding: 20px; }}
                .container {{ background: white; width: 90%; max-width: 1000px; margin: 0 auto; padding: 30px; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }}
                .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 3px solid #4CAF50; padding-bottom: 15px; margin-bottom: 20px; }}
                .header h1 {{ color: #2E7D32; margin: 0; font-size: 24px; text-transform: uppercase; }}
                .info {{ font-size: 14px; color: #555; text-align: right; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 14px; }}
                th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #ddd; }}
                th {{ background-color: #4CAF50; color: white; text-transform: uppercase; font-size: 13px; }}
                tr:hover {{ background-color: #f9f9f9; }}
                .positivo {{ color: #2E7D32; font-weight: bold; }}
                .negativo {{ color: #D32F2F; font-weight: bold; }}
                .footer {{ text-align: center; margin-top: 30px; font-size: 12px; color: #888; border-top: 1px solid #eee; padding-top: 10px; }}
                @media print {{
                    body {{ background-color: white; padding: 0; }}
                    .container {{ width: 100%; box-shadow: none; padding: 0; }}
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Extracto de Entradas y Salidas</h1>
                    <div class="info">
                        <strong>Fecha de Emisión:</strong> {ahora_str}<br>
                        <strong>Administrador:</strong> {usuario_actual}
                    </div>
                </div>
                <table>
                    <thead>
                        <tr>
                            <th>Fecha y Hora</th>
                            <th>Tienda / Sucursal</th>
                            <th>Producto</th>
                            <th>Cantidad (Movimiento)</th>
                            <th>Usuario</th>
                        </tr>
                    </thead>
                    <tbody>
                        {filas_html}
                    </tbody>
                </table>
                <div class="footer">
                    Reporte Global Diario - Sistema Centralizado de Inventarios
                </div>
            </div>
        </body>
        </html>
        """

        for sucursal, datos in reporte_mov.items():
            texto_txt += f"\n🏠 SUCURSAL: {sucursal}\n"
            texto_txt += "-"*75 + "\n"
            texto_txt += "🟢 ENTRADAS:\n"
            if not datos["Entradas"]: texto_txt += "   (Ninguna)\n"
            for e in datos["Entradas"]: texto_txt += f"   • {e}\n"
            
            texto_txt += "\n🔴 SALIDAS (Ajustes y Traspasos):\n"
            if not datos["Salidas"]: texto_txt += "   (Ninguna)\n"
            for s in datos["Salidas"]: texto_txt += f"   • {s}\n"
            
            texto_txt += "\n🛒 VENTAS:\n"
            if not datos["Ventas"]: texto_txt += "   (Ninguna)\n"
            for v in datos["Ventas"]: texto_txt += f"   • {v}\n"
            texto_txt += "="*75 + "\n"

        nombre_archivo_base = f"Extracto_Global_{hoy}_{ahora_arch}"
        ruta_completa_base = os.path.abspath(os.path.join(subcarpeta, nombre_archivo_base))
       
        with open(f"{ruta_completa_base}.txt", "w", encoding="utf-8") as f:
            f.write(texto_txt)
            
        ruta_html = f"{ruta_completa_base}.html"
        with open(ruta_html, "w", encoding="utf-8") as f:
            f.write(html_content)
            
        webbrowser.open(f"file://{ruta_html}")
           
    except Exception as e:
        messagebox.showerror("Error", f"No se pudo generar el reporte global:\n{e}")

def ajustar_stock_directo(tipo):
    producto = combo_productos.get()
    try:
        cantidad = int(spin_cantidad.get())
        if normalizar_texto(producto) not in lista_productos:
            messagebox.showwarning("Error", "Selecciona un producto válido.")
            return
        msg = "¿Aumentar" if tipo == "Suma" else "¿Retirar"
        if not messagebox.askyesno("Confirmar Ajuste", f"{msg} {cantidad} unidades de {producto}?"):
            return
        
        fila_idx = obtener_fila_producto(producto)
        if fila_idx == -1: return
        
        try:
            stock_str = hoja_inventario.cell(fila_idx, COL_INDEX).value
            stock_actual = int(stock_str) if stock_str else 0
        except Exception:
            stock_actual = 0
            
        nuevo_valor = stock_actual + cantidad if tipo == "Suma" else stock_actual - cantidad
        if nuevo_valor < 0:
            messagebox.showerror("Error", "El stock no puede ser negativo.")
            return
        
        hoja_inventario.update_cell(fila_idx, COL_INDEX, nuevo_valor)
        fecha_h = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if tipo == "Suma":
            texto_movimiento = f"+{cantidad} (AGREGA STOCK)"
        else:
            texto_movimiento = f"-{cantidad} (STOCK CORREGIDO)"
            
        hoja_historial.append_row([fecha_h, NOMBRE_TIENDA, producto, texto_movimiento, usuario_actual, 0, 0, 0])
        messagebox.showinfo("Éxito", f"Ajuste realizado. Nuevo stock: {nuevo_valor}")
        consultar_stock_inmediato()
    except Exception as e:
        messagebox.showerror("Error", f"Verifica la cantidad. Detalle: {e}")

def abrir_ventana_traspaso():
    producto = normalizar_texto(combo_productos.get())
    if not producto or producto not in lista_productos:
        messagebox.showwarning("Aviso", "Primero selecciona el producto que deseas traspasar.")
        return
        
    top = tk.Toplevel(ventana)
    top.title("Traspaso de Mercadería")
    top.geometry("500x350")
    top.configure(bg="#f5f5f5")
    top.grab_set() 
    
    tk.Label(top, text=f"📦 Producto a Traspasar:", font=("Arial", 12), bg="#f5f5f5").pack(pady=(15,0))
    tk.Label(top, text=f"{producto}", font=("Arial", 16, "bold"), fg="#1976D2", bg="#f5f5f5").pack(pady=(0,15))
    
    tk.Label(top, text="Sucursal Destino:", font=("Arial", 14), bg="#f5f5f5").pack(pady=5)
    sucursales_destino = [s for s in COLUMNAS_TIENDA.keys() if s != NOMBRE_TIENDA]
    combo_destino = ttk.Combobox(top, values=sucursales_destino, state="readonly", font=("Arial", 14))
    combo_destino.pack(pady=5)
    if sucursales_destino:
        combo_destino.current(0)
        
    tk.Label(top, text="Cantidad a enviar:", font=("Arial", 14), bg="#f5f5f5").pack(pady=5)
    spin_cant_traspaso = tk.Spinbox(top, from_=1, to=999, width=10, font=("Arial", 16))
    spin_cant_traspaso.pack(pady=5)
    
    def ejecutar():
        destino = combo_destino.get()
        try:
            cantidad = int(spin_cant_traspaso.get())
            if cantidad <= 0: raise ValueError
        except:
            messagebox.showerror("Error", "Cantidad inválida.", parent=top)
            return
            
        if not destino:
            messagebox.showerror("Error", "Selecciona un destino.", parent=top)
            return
            
        if not messagebox.askyesno("Confirmar", f"¿Enviar {cantidad} unidades de {producto}\ndesde {NOMBRE_TIENDA} hacia {destino}?", parent=top):
            return
            
        etiqueta_estado.config(text="Realizando traspaso...", fg="orange")
        ventana.update()
        
        try:
            fila_idx = obtener_fila_producto(producto)
            if fila_idx == -1: raise Exception("Producto no encontrado en la base de datos.")
            
            col_origen = COLUMNAS_TIENDA[NOMBRE_TIENDA]
            col_destino = COLUMNAS_TIENDA[destino]
            
            stock_orig_str = hoja_inventario.cell(fila_idx, col_origen).value
            stock_dest_str = hoja_inventario.cell(fila_idx, col_destino).value
            
            stock_orig = int(stock_orig_str) if stock_orig_str else 0
            stock_dest = int(stock_dest_str) if stock_dest_str else 0
            
            if stock_orig < cantidad:
                messagebox.showerror("Error", f"No hay suficiente stock en {NOMBRE_TIENDA}.\nStock actual: {stock_orig}", parent=top)
                etiqueta_estado.config(text="Listo para vender", fg="gray")
                return
            
            hoja_inventario.update_cell(fila_idx, col_origen, stock_orig - cantidad)
            hoja_inventario.update_cell(fila_idx, col_destino, stock_dest + cantidad)
            
            fecha_h = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            hoja_historial.append_row([fecha_h, NOMBRE_TIENDA, producto, f"-{cantidad} (TRASPASO A {destino})", usuario_actual, 0, 0, 0])
            hoja_historial.append_row([fecha_h, destino, producto, f"+{cantidad} (TRASPASO DE {NOMBRE_TIENDA})", usuario_actual, 0, 0, 0])
            
            messagebox.showinfo("Éxito", f"Se traspasaron {cantidad} unidades a {destino}.", parent=top)
            top.destroy()
            
            consultar_stock_inmediato()
            etiqueta_estado.config(text="Traspaso completado ✅", fg="green")
            
        except Exception as e:
            messagebox.showerror("Error", f"Fallo al traspasar:\n{e}", parent=top)
            etiqueta_estado.config(text="Error en traspaso", fg="red")
            
    tk.Button(top, text="Confirmar Traspaso", command=ejecutar, bg="#FF9800", fg="white", font=("Arial", 14, "bold"), pady=5).pack(pady=20)

# --- 4. FUNCIONES DE VENTA Y PRECIOS ---
def actualizar_precio_bs(*args):
    try:
        usd = float(precio_usd_var.get())
        dolar = float(valor_dolar_var.get())
        extra = float(adicional_var.get()) 
        
        bs_mayor = usd * dolar
        bs_menor = bs_mayor + extra
        
        precio_bs_var.set(f"{bs_mayor:.2f} Bs")
        precio_cobrar_var.set(f"{bs_mayor:.2f}") 
        precio_menor_var.set(f"{bs_menor:.2f}")  
        
        try:
            precio_mayor_usd_var.set(f"(${usd:.2f})")
        except NameError:
            pass
            
    except ValueError:
        precio_bs_var.set("0.00 Bs")
        precio_cobrar_var.set("0.00")
        precio_menor_var.set("0.00")
        try:
            precio_mayor_usd_var.set("($0.00)")
        except NameError:
            pass

def actualizar_menor_usd_desde_bs(*args):
    global actualizando_precios
    if actualizando_precios: return
    try:
        menor_bs = float(precio_menor_var.get())
        dolar = float(valor_dolar_var.get())
        if dolar > 0:
            actualizando_precios = True
            precio_menor_usd_var.set(f"{menor_bs/dolar:.2f}")
            actualizando_precios = False
    except Exception:
        pass

def actualizar_menor_bs_desde_usd(*args):
    global actualizando_precios
    if actualizando_precios: return
    try:
        menor_usd = float(precio_menor_usd_var.get())
        dolar = float(valor_dolar_var.get())
        if dolar > 0:
            actualizando_precios = True
            precio_menor_var.set(f"{menor_usd*dolar:.2f}")
            actualizando_precios = False
    except Exception:
        pass

def consultar_stock_inmediato(event=None):
    producto = normalizar_texto(combo_productos.get())
    if producto in lista_productos:
        etiqueta_stock_real.config(text="Consultando base de datos...", fg="blue")
        ventana.update_idletasks()
        try:
            fila_idx = obtener_fila_producto(producto)
            if fila_idx == -1: return
            fila_datos = hoja_inventario.row_values(fila_idx)
           
            s1 = fila_datos[3] if len(fila_datos) > 3 else "0"
            s2 = fila_datos[4] if len(fila_datos) > 4 else "0"
            s3 = fila_datos[5] if len(fila_datos) > 5 else "0"
            s4 = fila_datos[6] if len(fila_datos) > 6 else "0"
            sg = fila_datos[7] if len(fila_datos) > 7 else "0"
            
            resumen = f"MI STORE CENTER: {s1} | GALERIA LA PAZ : {s2} | AZTLAN: {s3} | UYUSMARKET: {s4}\n📦 STOCK GLOBAL: {sg}"
            etiqueta_stock_real.config(text=resumen, fg="#333")
           
            global stock_local_disponible
            stock_local_disponible = int(fila_datos[COL_INDEX - 1]) if len(fila_datos) >= COL_INDEX else 0
           
            try:
                precio_db = fila_datos[COL_PRECIO_USD - 1]
                if not precio_db: precio_db = "0.00"
            except IndexError:
                precio_db = "0.00"
                
            try:
                adicional_db = fila_datos[COL_PRECIO_ADICIONAL - 1]
                if not adicional_db: adicional_db = "0.00"
            except IndexError:
                adicional_db = "0.00"
            
            adicional_var.set(str(adicional_db))
            precio_usd_var.set(str(precio_db))
           
        except Exception as e:
            etiqueta_stock_real.config(text="Error al leer inventario", fg="red")
            print(f"Error consultando: {e}")
    else:
        etiqueta_stock_real.config(text="Busca un producto para ver stock", fg="gray")
        precio_usd_var.set("0.00")
        adicional_var.set("0.00")

def filtrar_lista(event):
    texto = normalizar_texto(combo_productos.get())
    filtrados = [p for p in lista_productos if texto in p] if texto else lista_productos
    combo_productos['values'] = filtrados
    consultar_stock_inmediato()

# --- LÓGICA DE TOTALES INDIVIDUALES ---
def actualizar_total_carrito():
    total_ref = sum(item["subtotal_ref"] for item in carrito)
    total_cobrado = sum(item["subtotal_cobrado"] for item in carrito)
   
    total_ref_var.set(f"{total_ref:.2f} Bs")
    total_real_var.set(f"{total_cobrado:.2f} Bs")

def añadir_al_carrito():
    producto = combo_productos.get()
    try:
        cantidad = int(spin_cantidad.get())
        precio_mayor_indiv = float(precio_cobrar_var.get()) 
        precio_menor_indiv = float(precio_menor_var.get())  
        extra_jefe = float(adicional_var.get())             
       
        if normalizar_texto(producto) not in lista_productos: return
        if cantidad > stock_local_disponible:
            messagebox.showerror("Sin Stock", f"No hay suficiente en {NOMBRE_TIENDA}.")
            return
           
        precio_referencial_base = precio_mayor_indiv + extra_jefe
        
        subtotal_ref = cantidad * precio_referencial_base
        subtotal_cobrado = cantidad * precio_menor_indiv
        
        diferencia = subtotal_cobrado - subtotal_ref
        
        dolar = float(valor_dolar_var.get())
        subtotal_cobrado_usd = subtotal_cobrado / dolar if dolar > 0 else 0.0
       
        carrito.append({
            "producto": normalizar_texto(producto),
            "cantidad": cantidad,
            "subtotal_ref": subtotal_ref,
            "subtotal_cobrado": subtotal_cobrado,
            "subtotal_cobrado_usd": subtotal_cobrado_usd,
            "diferencia": diferencia
        })
       
        lista_visual_carrito.insert(tk.END, f"{producto} (x{cantidad}) - {subtotal_cobrado:.2f} Bs")
       
        actualizar_total_carrito()
        combo_productos.set('')
        precio_usd_var.set("0.00")
        adicional_var.set("0.00")
        etiqueta_stock_real.config(text="Busca un producto para ver stock", fg="gray")
    except ValueError:
        messagebox.showerror("Error", "Revisa la cantidad o el precio a cobrar.")

def deshacer_ultimo():
    if carrito:
        item_removido = carrito.pop()
        lista_visual_carrito.delete(lista_visual_carrito.size() - 1)
        actualizar_total_carrito()
        etiqueta_estado.config(text=f"Se quitó: {item_removido['producto']}", fg="orange")
    else:
        messagebox.showinfo("Aviso", "El carrito ya está vacío.")

def vaciar_carrito():
    carrito.clear()
    lista_visual_carrito.delete(0, tk.END)
    actualizar_total_carrito()
    etiqueta_estado.config(text="Carrito vaciado", fg="gray")

def generar_comprobante(items_vendidos, total_real, fecha_hora_str):
    mes, anio = obtener_mes_actual()
    carpeta_base = "Comprobantes"
    subcarpeta = os.path.join(carpeta_base, f"Comprobantes_{mes}_{anio}")
    if not os.path.exists(subcarpeta):
        os.makedirs(subcarpeta)

    nombre_tienda_seguro = NOMBRE_TIENDA.replace(" ", "_")
    fecha_archivo = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre_base = f"Factura_{nombre_tienda_seguro}_{fecha_archivo}"
    ruta_base = os.path.abspath(os.path.join(subcarpeta, nombre_base))
    
    try:
        dolar_actual = float(valor_dolar_var.get())
        total_real_usd = total_real / dolar_actual if dolar_actual > 0 else 0.0
    except:
        total_real_usd = 0.0
   
    html_content = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>Comprobante de Venta</title>
        <style>
            body {{ font-family: 'Courier New', Courier, monospace; background-color: #f4f4f4; padding: 20px; }}
            .ticket {{ background: white; width: 320px; margin: 0 auto; padding: 20px; border-radius: 5px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }}
            h2 {{ text-align: center; margin-bottom: 5px; color: #333; }}
            .header-info {{ text-align: center; font-size: 14px; color: #666; margin-bottom: 20px; }}
            .divider {{ border-bottom: 1px dashed #999; margin: 10px 0; }}
            table {{ width: 100%; font-size: 14px; border-collapse: collapse; }}
            th, td {{ padding: 5px 0; text-align: left; }}
            th {{ border-bottom: 1px solid #ddd; }}
            .right {{ text-align: right; }}
            .total-row {{ font-weight: bold; font-size: 18px; }}
            .footer {{ text-align: center; font-size: 14px; margin-top: 20px; color: #666; }}
           
            @media print {{
                body {{ background-color: white; padding: 0; }}
                .ticket {{ box-shadow: none; width: 100%; max-width: 320px; }}
            }}
        </style>
    </head>
    <body>
        <div class="ticket">
            <h2>{NOMBRE_TIENDA}</h2>
            <div class="header-info">
                COMPROBANTE DE VENTA<br>
                Fecha: {fecha_hora_str}<br>
                Cajero: {usuario_actual}
            </div>
           
            <div class="divider"></div>
           
            <table>
                <tr>
                    <th>Cant</th>
                    <th>Producto</th>
                    <th class="right">Subt. Bs</th>
                    <th class="right">Subt. $us</th>
                </tr>
    """
   
    for item in items_vendidos:
        html_content += f"""
                <tr>
                    <td>{item['cantidad']}</td>
                    <td>{item['producto']}</td>
                    <td class="right">{item['subtotal_cobrado']:.2f}</td>
                    <td class="right">{item['subtotal_cobrado_usd']:.2f}</td>
                </tr>
        """
       
    html_content += f"""
            </table>
           
            <div class="divider"></div>
           
            <table>
                <tr class="total-row">
                    <td>TOTAL Bs:</td>
                    <td class="right">{total_real:.2f}</td>
                </tr>
                <tr class="total-row">
                    <td>TOTAL $us:</td>
                    <td class="right">{total_real_usd:.2f}</td>
                </tr>
            </table>
           
            <div class="footer">
                ¡Gracias por su preferencia!<br>
                Vuelva pronto.
            </div>
        </div>
    </body>
    </html>
    """
   
    texto_recibo = f"--- {NOMBRE_TIENDA} ---\nFecha: {fecha_hora_str}\nTOTAL COBRADO: {total_real:.2f} Bs | {total_real_usd:.2f} $us"
    try:
        with open(f"{ruta_base}.txt", "w", encoding="utf-8") as f:
            f.write(texto_recibo)
    except Exception as e:
        print(f"Error guardando txt: {e}")

    ruta_html = f"{ruta_base}.html"
    try:
        with open(ruta_html, "w", encoding="utf-8") as f:
            f.write(html_content)
        webbrowser.open(f"file://{ruta_html}")
    except Exception as e:
        print(f"Error generando HTML: {e}")

def registrar_venta_final():
    if not carrito:
        messagebox.showwarning("Carrito vacío", "No hay productos.")
        return

    total_real_cobrado = sum(item["subtotal_cobrado"] for item in carrito)

    if not messagebox.askyesno("Confirmar", f"¿Finalizar venta por un total de {total_real_cobrado:.2f} Bs?"): return
   
    etiqueta_estado.config(text="Actualizando nube...", fg="orange")
    ventana.update()
   
    try:
        filas_historial = []
        fecha_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        carrito_copia = list(carrito)
       
        for item in carrito:
            fila_idx = obtener_fila_producto(item["producto"])
            if fila_idx == -1: continue
            
            try:
                stock_str = hoja_inventario.cell(fila_idx, COL_INDEX).value
                stock_actual = int(stock_str) if stock_str else 0
            except:
                stock_actual = 0
                
            hoja_inventario.update_cell(fila_idx, COL_INDEX, stock_actual - item["cantidad"])
           
            filas_historial.append([
                fecha_hora,
                NOMBRE_TIENDA,
                item["producto"],
                f"-{item['cantidad']} (VENTA)",
                usuario_actual,
                round(item['subtotal_ref'], 2),
                round(item['diferencia'], 2),
                round(item['subtotal_cobrado'], 2)
            ])
       
        hoja_historial.append_rows(filas_historial)
       
        generar_comprobante(carrito_copia, total_real_cobrado, fecha_hora)
       
        messagebox.showinfo("Éxito", "Venta guardada. El comprobante se ha abierto en tu navegador web.")
        vaciar_carrito()
        etiqueta_estado.config(text="Venta completada ✅", fg="green")
    except Exception as e:
        messagebox.showerror("Error", str(e))

# --- 5. INTERFAZ PRINCIPAL AUTO-AJUSTABLE ---
def abrir_sistema_principal():
    global ventana, combo_productos, combo_categoria, combo_marca, etiqueta_stock_real, spin_cantidad
    global lista_visual_carrito, etiqueta_estado, valor_dolar_var, adicional_var
    global precio_usd_var, precio_bs_var, precio_cobrar_var, precio_menor_var, total_ref_var, total_real_var
    global precio_mayor_usd_var, precio_menor_usd_var
   
    ventana = tk.Tk()
    ventana.title(f"POS - {NOMBRE_TIENDA} | Usuario: {usuario_actual}")
    ventana.state('zoomed')
    ventana.update_idletasks() 
   
    try:
        valor_guardado = hoja_inventario.cell(CELDA_DOLAR_FILA, CELDA_DOLAR_COL).value
        if not valor_guardado: valor_guardado = "10.00"
    except:
        valor_guardado = "10.00"
       
    valor_dolar_var = tk.StringVar(value=str(valor_guardado))
    precio_usd_var = tk.StringVar(value="0.00")
    adicional_var = tk.StringVar(value="0.00") 
    precio_bs_var = tk.StringVar(value="0.00 Bs")
    precio_cobrar_var = tk.StringVar(value="0.00")
    precio_menor_var = tk.StringVar(value="0.00")
    
    precio_mayor_usd_var = tk.StringVar(value="($0.00)") 
    precio_menor_usd_var = tk.StringVar(value="0.00") 
   
    total_ref_var = tk.StringVar(value="0.00 Bs")
    total_real_var = tk.StringVar(value="0.00 Bs")
   
    precio_usd_var.trace_add("write", actualizar_precio_bs)
    valor_dolar_var.trace_add("write", actualizar_precio_bs)
    adicional_var.trace_add("write", actualizar_precio_bs) 
    
    precio_menor_var.trace_add("write", actualizar_menor_usd_desde_bs) 
    precio_menor_usd_var.trace_add("write", actualizar_menor_bs_desde_usd) 

    tk.Label(ventana, text=f"SESIÓN ACTIVA: {usuario_actual} | ROL: {cargo_actual} | SUCURSAL: {NOMBRE_TIENDA}",
             bg="#1c1c1c", fg="white", font=("Arial", 14, "bold"), pady=5).pack(fill="x")

    ancho_pantalla = ventana.winfo_screenwidth()
    if cargo_actual == "JEFE":
        ancho_izq = int(ancho_pantalla * 0.60) 
    else:
        ancho_izq = int(ancho_pantalla * 0.70) 

    panel_principal = tk.PanedWindow(ventana, orient=tk.HORIZONTAL, bg="#cccccc", sashwidth=6)
    panel_principal.pack(fill="both", expand=True)

    # ======================================================================================
    # LADO IZQUIERDO (CON SISTEMA DE SCROLL)
    # ======================================================================================
    frame_izquierdo_base = tk.Frame(panel_principal, bg="#f5f5f5")
    panel_principal.add(frame_izquierdo_base, width=ancho_izq)

    canvas_izq = tk.Canvas(frame_izquierdo_base, bg="#f5f5f5", highlightthickness=0)
    scrollbar_izq = ttk.Scrollbar(frame_izquierdo_base, orient="vertical", command=canvas_izq.yview)
    canvas_izq.configure(yscrollcommand=scrollbar_izq.set)

    scrollbar_izq.pack(side="right", fill="y")
    canvas_izq.pack(side="left", fill="both", expand=True)

    frame_izquierdo = tk.Frame(canvas_izq, bg="#f5f5f5")
    canvas_window = canvas_izq.create_window((0, 0), window=frame_izquierdo, anchor="nw")

    def configurar_scroll(event):
        canvas_izq.configure(scrollregion=canvas_izq.bbox("all"))

    def configurar_ancho_canvas(event):
        canvas_izq.itemconfig(canvas_window, width=event.width)

    frame_izquierdo.bind("<Configure>", configurar_scroll)
    canvas_izq.bind("<Configure>", configurar_ancho_canvas)

    def _scroll_raton_izq(event):
        canvas_izq.yview_scroll(int(-1*(event.delta/120)), "units")
    
    canvas_izq.bind("<Enter>", lambda e: canvas_izq.bind_all("<MouseWheel>", _scroll_raton_izq))
    canvas_izq.bind("<Leave>", lambda e: canvas_izq.unbind_all("<MouseWheel>"))

    frame_superior = tk.Frame(frame_izquierdo, bg="#f5f5f5")
    frame_superior.pack(fill="x")

    frame_sel = tk.LabelFrame(frame_superior, text=" Registro de Productos ", padx=10, pady=10, font=("Arial", 15, "bold"))
    frame_sel.pack(pady=10, fill="x", padx=20)

    frame_filtros = tk.Frame(frame_sel, bg="#f5f5f5")
    frame_filtros.pack(fill="x", pady=5)

    tk.Label(frame_filtros, text="Categoría:", font=("Arial", 14, "bold"), bg="#f5f5f5").pack(side="left")
    combo_categoria = ttk.Combobox(frame_filtros, width=12, state="readonly", font=("Arial", 14))
    combo_categoria['values'] = categorias_unicas
    combo_categoria.pack(side="left", padx=3)
    combo_categoria.bind("<<ComboboxSelected>>", al_seleccionar_categoria)

    tk.Label(frame_filtros, text="Marca:", font=("Arial", 14, "bold"), bg="#f5f5f5").pack(side="left", padx=(5,0))
    combo_marca = ttk.Combobox(frame_filtros, width=12, state="readonly", font=("Arial", 14))
    combo_marca.pack(side="left", padx=3)
    combo_marca.bind("<<ComboboxSelected>>", al_seleccionar_marca)

    tk.Label(frame_filtros, text="Modelo:", font=("Arial", 14, "bold"), bg="#f5f5f5").pack(side="left", padx=(5,0))
    combo_productos = ttk.Combobox(frame_filtros, width=20, font=("Arial", 15))
    combo_productos['values'] = lista_productos
    combo_productos.pack(side="left", padx=3)
    combo_productos.bind("<<ComboboxSelected>>", consultar_stock_inmediato)
    combo_productos.bind("<KeyRelease>", filtrar_lista)

    tk.Button(frame_filtros, text="🔄 Actualizar Todo", command=refrescar_datos_nube, bg="#2196F3", fg="white", font=("Arial", 13, "bold")).pack(side="left", padx=10)

    etiqueta_stock_real = tk.Label(frame_sel, text="Busca un producto para ver stock", font=("Consolas", 16), bg="#e0e0e0", pady=10)
    etiqueta_stock_real.pack(pady=5, fill="x")

    frame_c = tk.Frame(frame_sel, bg="#f5f5f5")
    frame_c.pack(pady=10)
    tk.Label(frame_c, text="Cantidad:", font=("Arial", 15, "bold"), bg="#f5f5f5").pack(side="left", padx=2)
    spin_cantidad = tk.Spinbox(frame_c, from_=1, to=999, width=4, font=("Arial", 15))
    spin_cantidad.pack(side="left", padx=2)
   
    tk.Label(frame_c, text="  |  Por Mayor (Bs):", font=("Arial", 14, "bold"), fg="gray", bg="#f5f5f5").pack(side="left", padx=2)
    entrada_precio_cobrar = tk.Entry(frame_c, textvariable=precio_cobrar_var, width=10, font=("Arial", 15, "bold"), justify="center", fg="gray", state="readonly")
    entrada_precio_cobrar.pack(side="left", padx=2)
    tk.Label(frame_c, textvariable=precio_mayor_usd_var, font=("Arial", 14, "bold"), fg="gray", bg="#f5f5f5").pack(side="left")
    
    tk.Label(frame_c, text="  |  Por Menor (Bs):", font=("Arial", 14, "bold"), fg="#1976D2", bg="#f5f5f5").pack(side="left", padx=2)
    entrada_precio_menor = tk.Entry(frame_c, textvariable=precio_menor_var, width=10, font=("Arial", 16, "bold"), justify="center", fg="#1976D2")
    entrada_precio_menor.pack(side="left", padx=2)
    
    tk.Label(frame_c, text="($):", font=("Arial", 14, "bold"), fg="#1976D2", bg="#f5f5f5").pack(side="left", padx=2)
    entrada_precio_menor_usd = tk.Entry(frame_c, textvariable=precio_menor_usd_var, width=10, font=("Arial", 16, "bold"), justify="center", fg="#1976D2")
    entrada_precio_menor_usd.pack(side="left", padx=2)

    tk.Button(frame_sel, text="➕ Añadir al Carrito", command=añadir_al_carrito,
              bg="#2196F3", fg="white", font=("Arial", 14, "bold"), pady=5).pack(fill="x", pady=5)
              
    tk.Button(frame_sel, text="📦 Traspasar a otra Sucursal", command=abrir_ventana_traspaso,
              bg="#8D6E63", fg="white", font=("Arial", 12, "bold"), pady=5).pack(fill="x", pady=(0, 5))

    if cargo_actual == "JEFE":
        frame_jefe = tk.Frame(frame_sel, bg="#f5f5f5")
        frame_jefe.pack(fill="x", pady=5)
        tk.Button(frame_jefe, text="⬆️ Aumentar Stock", command=lambda: ajustar_stock_directo("Suma"),
                  bg="#6A1B9A", fg="white", font=("Arial", 13, "bold")).pack(side="left", expand=True, fill="x", padx=2)
        tk.Button(frame_jefe, text="⬇️ Retirar Stock", command=lambda: ajustar_stock_directo("Resta"),
                  bg="#AD1457", fg="white", font=("Arial", 13, "bold")).pack(side="left", expand=True, fill="x", padx=2)

        # REPORTES
        frame_reportes_jefe = tk.Frame(frame_sel, bg="#f5f5f5")
        frame_reportes_jefe.pack(fill="x", pady=10)
        
        frame_reporte_izq = tk.Frame(frame_reportes_jefe, bg="#e3f2fd", bd=1, relief=tk.SOLID, padx=5, pady=5)
        frame_reporte_izq.pack(fill="x", pady=2)
        tk.Label(frame_reporte_izq, text="Sucursal:", bg="#e3f2fd", font=("Arial", 14, "bold")).pack(side="left", padx=5)
        combo_tienda_reporte = ttk.Combobox(frame_reporte_izq, values=["MI STORE CENTER", "GALERIA LA PAZ", "AZTLAN", "UYUSMARKET"], state="readonly", width=18, font=("Arial", 14))
        combo_tienda_reporte.set(NOMBRE_TIENDA)
        combo_tienda_reporte.pack(side="left", padx=5)
        tk.Button(frame_reporte_izq, text="📊 GENERAR REPORTE", command=lambda: generar_reporte_diario(combo_tienda_reporte.get()), bg="#FF9800", fg="white", font=("Arial", 13, "bold")).pack(side="right", fill="x", expand=True, padx=5)

        frame_reporte_global = tk.Frame(frame_reportes_jefe, bg="#e8f5e9", bd=1, relief=tk.SOLID, padx=5, pady=5)
        frame_reporte_global.pack(fill="x", pady=2)
        tk.Label(frame_reporte_global, text="Movimientos del día (Todas las sucursales):", bg="#e8f5e9", font=("Arial", 12, "bold")).pack(side="left", padx=5)
        tk.Button(frame_reporte_global, text="🌍 REPORTE GLOBAL ENTRADAS/SALIDAS", command=generar_reporte_global_movimientos, bg="#4CAF50", fg="white", font=("Arial", 12, "bold")).pack(side="right", fill="x", expand=True, padx=5)


    tk.Label(frame_izquierdo, text="Carrito de Compras:", font=("Arial", 15, "bold"), bg="#f5f5f5").pack(pady=5)
    lista_visual_carrito = tk.Listbox(frame_izquierdo, height=10, font=("Arial", 15))
    lista_visual_carrito.pack(fill="both", padx=20, expand=True)

    frame_inferior = tk.Frame(frame_izquierdo, bg="#f5f5f5")
    frame_inferior.pack(fill="x", pady=(10, 30))

    tk.Button(frame_inferior, text="🗑️ Vaciar Carrito", command=vaciar_carrito,
              fg="red", relief="flat", font=("Arial", 14, "underline"), bg="#f5f5f5").pack(pady=5)

    etiqueta_estado = tk.Label(frame_inferior, text="Listo para vender", fg="gray", font=("Arial", 14), bg="#f5f5f5")
    etiqueta_estado.pack(pady=5)

    tk.Button(frame_inferior, text="FINALIZAR VENTA Y ACTUALIZAR NUBE", command=registrar_venta_final,
              bg="#388E3C", fg="white", font=("Arial", 17, "bold"), pady=15).pack(pady=10, fill="x", padx=20)


    # ======================================================================================
    # LADO DERECHO (CON SISTEMA DE SCROLL)
    # ======================================================================================
    frame_derecho_base = tk.Frame(panel_principal, bg="#ffffff")
    panel_principal.add(frame_derecho_base)

    canvas_der = tk.Canvas(frame_derecho_base, bg="#ffffff", highlightthickness=0)
    scrollbar_der = ttk.Scrollbar(frame_derecho_base, orient="vertical", command=canvas_der.yview)
    canvas_der.configure(yscrollcommand=scrollbar_der.set)

    scrollbar_der.pack(side="right", fill="y")
    canvas_der.pack(side="left", fill="both", expand=True)

    frame_derecho = tk.Frame(canvas_der, bg="#ffffff")
    canvas_window_der = canvas_der.create_window((0, 0), window=frame_derecho, anchor="nw")

    def configurar_scroll_der(event):
        canvas_der.configure(scrollregion=canvas_der.bbox("all"))

    def configurar_ancho_canvas_der(event):
        canvas_der.itemconfig(canvas_window_der, width=event.width)

    frame_derecho.bind("<Configure>", configurar_scroll_der)
    canvas_der.bind("<Configure>", configurar_ancho_canvas_der)

    def _scroll_raton_der(event):
        canvas_der.yview_scroll(int(-1*(event.delta/120)), "units")

    canvas_der.bind("<Enter>", lambda e: canvas_der.bind_all("<MouseWheel>", _scroll_raton_der))
    canvas_der.bind("<Leave>", lambda e: canvas_der.unbind_all("<MouseWheel>"))
    # --------------------------------------------------------
   
    frame_dolar = tk.LabelFrame(frame_derecho, text=" Cotización del Dólar ", bd=2, relief=tk.GROOVE, padx=10, pady=10, font=("Arial", 15, "bold"), bg="#ffffff")
    frame_dolar.pack(anchor=tk.N, padx=20, pady=(30, 10), fill="x")
   
    tk.Label(frame_dolar, text="Valor actual (Bs por 1 USD):", font=("Arial", 14), bg="#ffffff").pack(pady=(5, 5))
   
    entrada_dolar = tk.Entry(frame_dolar, textvariable=valor_dolar_var, width=15, font=("Arial", 20, "bold"), justify='center')
    entrada_dolar.pack(pady=5)
   
    btn_actualizar_dolar = tk.Button(frame_dolar, text="Actualizar Tipo de Cambio", command=actualizar_dolar, bg="#4CAF50", fg="white", font=("Arial", 14, "bold"), pady=5)
    btn_actualizar_dolar.pack(fill="x", pady=(5, 0))

    frame_precios = tk.LabelFrame(frame_derecho, text=" Precio Base del Producto ", bd=2, relief=tk.GROOVE, padx=10, pady=10, font=("Arial", 15, "bold"), bg="#ffffff")
    frame_precios.pack(anchor=tk.N, padx=20, pady=10, fill="x")
   
    frame_inner_precios = tk.Frame(frame_precios, bg="#ffffff")
    frame_inner_precios.pack(fill="x", pady=5)
    frame_inner_precios.columnconfigure(0, weight=1)
    frame_inner_precios.columnconfigure(1, weight=1)
    frame_inner_precios.columnconfigure(2, weight=1)
    frame_inner_precios.columnconfigure(3, weight=1)

    tk.Label(frame_inner_precios, text="USD ($):", bg="#ffffff", font=("Arial", 14, "bold")).grid(row=0, column=0, sticky="e", padx=2)
    entrada_precio_usd = tk.Entry(frame_inner_precios, textvariable=precio_usd_var, width=10, font=("Arial", 16, "bold"), justify="center")
    entrada_precio_usd.grid(row=0, column=1, sticky="w", padx=2)
   
    tk.Label(frame_inner_precios, text="= Mayor Bs:", bg="#ffffff", font=("Arial", 14, "bold")).grid(row=0, column=2, sticky="e", padx=2)
    tk.Label(frame_inner_precios, textvariable=precio_bs_var, bg="#ffffff", fg="#555", font=("Arial", 16, "bold")).grid(row=0, column=3, sticky="w", padx=2)
    
    tk.Label(frame_inner_precios, text="+ Extra Menor (Bs):", bg="#ffffff", font=("Arial", 14, "bold"), fg="#1976D2").grid(row=1, column=0, columnspan=2, sticky="e", padx=2, pady=5)
    entrada_adicional = tk.Entry(frame_inner_precios, textvariable=adicional_var, width=10, font=("Arial", 16, "bold"), justify="center", fg="#1976D2")
    entrada_adicional.grid(row=1, column=2, sticky="w", padx=2, pady=5)
   
    btn_guardar_precio = tk.Button(frame_precios, text="💾 Guardar Precios", command=guardar_precios_nube, bg="#1976D2", fg="white", font=("Arial", 14, "bold"), pady=5)
    btn_guardar_precio.pack(fill="x", pady=(5, 0))

    frame_cobro = tk.LabelFrame(frame_derecho, text=" Resumen de Venta ", bd=2, relief=tk.GROOVE, padx=10, pady=10, font=("Arial", 15, "bold"), bg="#e8f5e9")
    frame_cobro.pack(anchor=tk.N, padx=20, pady=10, fill="x")

    frame_inner_cobro = tk.Frame(frame_cobro, bg="#e8f5e9")
    frame_inner_cobro.pack(fill="x", pady=5)
    frame_inner_cobro.columnconfigure(0, weight=1)
    frame_inner_cobro.columnconfigure(1, weight=1)

    tk.Label(frame_inner_cobro, text="REF MAYOR (Bs):", font=("Arial", 14, "bold"), bg="#e8f5e9", fg="#555").grid(row=0, column=0, pady=(0,5))
    tk.Label(frame_inner_cobro, text="COBRO FINAL (Bs):", font=("Arial", 15, "bold"), bg="#e8f5e9", fg="#d32f2f").grid(row=0, column=1, pady=(0,5))

    tk.Label(frame_inner_cobro, textvariable=total_ref_var, font=("Arial", 18, "bold"), bg="#e8f5e9", fg="#555").grid(row=1, column=0)
    tk.Label(frame_inner_cobro, textvariable=total_real_var, font=("Arial", 24, "bold"), bg="#e8f5e9", fg="#d32f2f").grid(row=1, column=1)

    btn_deshacer = tk.Button(frame_cobro, text="↩️ Deshacer Último", command=deshacer_ultimo, bg="#FFB300", fg="#333", font=("Arial", 14, "bold"), pady=5)
    btn_deshacer.pack(fill="x", pady=(10, 0))

    if cargo_actual != "JEFE":
        entrada_dolar.config(state="readonly")
        btn_actualizar_dolar.config(state="disabled")
        tk.Label(frame_dolar, text="(Solo lectura)", font=("Arial", 12), fg="gray", bg="#ffffff").pack(pady=5)
       
        entrada_precio_usd.config(state="readonly")
        entrada_adicional.config(state="readonly")
        btn_guardar_precio.config(state="disabled")
        tk.Label(frame_precios, text="(Solo lectura)", font=("Arial", 12), fg="gray", bg="#ffffff").pack(pady=5)

    if cargo_actual == "JEFE":
        frame_gestion = tk.LabelFrame(frame_derecho, text=" Cierre y Gestión ", bd=2, relief=tk.GROOVE, padx=10, pady=10, font=("Arial", 15, "bold"), bg="#ffffff")
        frame_gestion.pack(anchor=tk.N, padx=20, pady=(10, 30), fill="x") # pady=(10,30) para dejar margen al final del scroll

        btn_archivar = tk.Button(frame_gestion, text="📂 Archivar Mes y Crear Nuevo", command=archivar_historial_mes, bg="#8E24AA", fg="white", font=("Arial", 14, "bold"), pady=5)
        btn_archivar.pack(fill="x", pady=5)

        btn_limpiar = tk.Button(frame_gestion, text="🗑️ Eliminar Historial Actual", command=limpiar_historial, bg="#D32F2F", fg="white", font=("Arial", 14, "bold"), pady=5)
        btn_limpiar.pack(fill="x", pady=5)

    ventana.mainloop()

# --- LOGIN ---
ventana_login = tk.Tk()
ventana_login.title("Acceso")
ventana_login.geometry("300x320")
tk.Label(ventana_login, text="USUARIO:", font=("Arial", 10, "bold")).pack(pady=(20,0))
entry_user = tk.Entry(ventana_login, font=("Arial", 11), justify="center")
entry_user.pack(pady=5)

tk.Label(ventana_login, text="CONTRASEÑA:", font=("Arial", 10, "bold")).pack(pady=(10,0))
entry_pw = tk.Entry(ventana_login, show="*"); entry_pw.pack(pady=5)

tk.Label(ventana_login, text="SUCURSAL:", font=("Arial", 10, "bold")).pack(pady=(10,0))
combo_sucursal = ttk.Combobox(ventana_login, values=["MI STORE CENTER", "GALERIA LA PAZ", "AZTLAN", "UYUSMARKET"], state="readonly", justify="center", font=("Arial", 11))
combo_sucursal.current(0)
combo_sucursal.pack(pady=5)

tk.Button(ventana_login, text="ACCEDER", command=validar_login, bg="#333", fg="white", font=("Arial", 11, "bold"), pady=5).pack(pady=20, fill="x", padx=40)

ventana_login.mainloop()
