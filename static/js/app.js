/**
 * Venta y Stock - Interactividad Web (Vanilla JS)
 * Replica exactamente el comportamiento dinámico de la versión CustomTkinter
 */

document.addEventListener("DOMContentLoaded", () => {
  inicializarMenuMobile();
  inicializarCalculadora();
  inicializarBlockNotas();
  inicializarPuntoVenta();
  inicializarAtajosTeclado();
});

// =========================================================================
// 0. NAVEGACIÓN MÓVIL / RESPONSIVE
// =========================================================================
// F1..F9 (menú lateral) + F10 (botón "Otros" de la pantalla de Ventas)
const TECLAS_ATAJO = /^F([1-9]|10)$/;

function inicializarAtajosTeclado() {
  window.addEventListener("keydown", (e) => {
    const tecla = e.key || (e.code && TECLAS_ATAJO.test(e.code) ? e.code : "");
    if (!TECLAS_ATAJO.test(tecla) || e.altKey || e.ctrlKey || e.metaKey) return;

    // No secuestrar F1-F7 mientras el usuario escribe; F8/F9 siempre son utilidades.
    const boton = buscarBotonAtajo(tecla);
    if (!boton) return;

    e.preventDefault();
    e.stopImmediatePropagation();
    boton.click();
  }, true);
}

// Si varios elementos comparten el mismo atajo (ej. F10 -> "Otros" en los dos
// modos de búsqueda), se prioriza el que está visible en pantalla.
function buscarBotonAtajo(tecla) {
  const candidatos = document.querySelectorAll(`[data-shortcut-key="${tecla}"]`);
  if (!candidatos.length) return null;
  for (const cand of candidatos) {
    if (cand.offsetParent !== null || cand.getClientRects().length > 0) return cand;
  }
  return candidatos[0];
}

function inicializarMenuMobile() {
  const sidebar = document.getElementById("sidebar");
  const backdrop = document.getElementById("sidebar-backdrop");

  window.toggleMenuMobile = () => {
    if (sidebar) sidebar.classList.toggle("open");
    if (backdrop) backdrop.classList.toggle("active");
  };

  window.cerrarMenuMobile = () => {
    if (sidebar) sidebar.classList.remove("open");
    if (backdrop) backdrop.classList.remove("active");
  };

  // Cerrar el menú al cambiar de pantalla o redimensionar a desktop
  window.addEventListener("resize", () => {
    if (window.innerWidth > 900) {
      window.cerrarMenuMobile();
    }
  });
}

// =========================================================================
// 1. CALCULADORA (Réplica exacta de ui/main_window.py)
// =========================================================================
let calcDisplayVal = "0";

function inicializarCalculadora() {
  const modal = document.getElementById("modal-calculadora");
  const display = document.getElementById("calc-display");
  if (!modal || !display) return;

  window.abrirCalculadora = () => {
    modal.classList.add("active");
    calcDisplayVal = "0";
    actualizarDisplay();
    display.focus();
  };

  window.cerrarCalculadora = () => {
    modal.classList.remove("active");
  };

  window.calcClick = (v) => {
    if (calcDisplayVal === "Error") calcDisplayVal = "";
    if (calcDisplayVal === "0" && !["/", "*", "+", "-", "."].includes(v)) {
      calcDisplayVal = "";
    }
    if (["/", "*", "+", "-", "%"].includes(v)) {
      if (calcDisplayVal && ["/", "*", "+", "-"].includes(calcDisplayVal.slice(-1))) {
        calcDisplayVal = calcDisplayVal.slice(0, -1);
      }
      if (calcDisplayVal && calcDisplayVal.slice(-1) === "%") return;
    }
    if (v === ".") {
      const parts = calcDisplayVal.split(/[\+\-\*\/]/);
      const cur = parts[parts.length - 1];
      if (cur.includes(".")) return;
    }
    calcDisplayVal += String(v);
    actualizarDisplay();
  };

  window.calcBorrar = () => {
    if (calcDisplayVal && calcDisplayVal !== "Error") {
      calcDisplayVal = calcDisplayVal.slice(0, -1) || "0";
      actualizarDisplay();
    }
  };

  window.calcLimpiar = () => {
    calcDisplayVal = "0";
    actualizarDisplay();
  };

  window.calcIgual = async () => {
    if (!calcDisplayVal || calcDisplayVal === "Error") return;
    try {
      const res = await fetch("/api/calculadora/calcular", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expresion: calcDisplayVal }),
      });
      const data = await res.json();
      if (data.ok) {
        calcDisplayVal = String(data.resultado);
      } else {
        calcDisplayVal = "Error";
      }
    } catch {
      calcDisplayVal = "Error";
    }
    actualizarDisplay();
  };

  function actualizarDisplay() {
    display.value = calcDisplayVal;
  }

  // Teclado físico para la calculadora
  window.addEventListener("keydown", (e) => {
    if (!modal.classList.contains("active")) return;
    if (e.key === "Escape") {
      window.cerrarCalculadora();
      return;
    }
    if (e.key === "Enter" || e.key === "=") {
      e.preventDefault();
      window.calcIgual();
      return;
    }
    if (e.key === "Backspace") {
      e.preventDefault();
      window.calcBorrar();
      return;
    }
    if ("0123456789+-*/.%".includes(e.key)) {
      e.preventDefault();
      window.calcClick(e.key);
      return;
    }
    if (e.key.toLowerCase() === "c") {
      e.preventDefault();
      window.calcLimpiar();
    }
  });
}

// =========================================================================
// 2. BLOCK DE NOTAS (Persistente 365 días)
// =========================================================================
let paginaActualNotas = 0;
const TOTAL_HOJAS_NOTAS = 365;
let timerGuardadoNotas = null;

function inicializarBlockNotas() {
  const modal = document.getElementById("modal-block-notas");
  const textarea = document.getElementById("notepad-text");
  if (!modal || !textarea) return;

  window.abrirBlockNotas = () => {
    modal.classList.add("active");
    cargarPaginaNota(paginaActualNotas);
    textarea.focus();
  };

  window.cerrarBlockNotas = () => {
    guardarNotaActual();
    modal.classList.remove("active");
  };

  window.notaAnterior = () => {
    if (paginaActualNotas > 0) {
      guardarNotaActual();
      paginaActualNotas--;
      cargarPaginaNota(paginaActualNotas);
    }
  };

  window.notaSiguiente = () => {
    if (paginaActualNotas < TOTAL_HOJAS_NOTAS - 1) {
      guardarNotaActual();
      paginaActualNotas++;
      cargarPaginaNota(paginaActualNotas);
    }
  };

  textarea.addEventListener("input", () => {
    clearTimeout(timerGuardadoNotas);
    timerGuardadoNotas = setTimeout(guardarNotaActual, 600);
  });

  async function cargarPaginaNota(pag) {
    document.getElementById("notepad-page-lbl").textContent = `Hoja ${pag + 1} de ${TOTAL_HOJAS_NOTAS}`;
    try {
      const res = await fetch(`/api/notas/${pag}`);
      const data = await res.json();
      textarea.value = data.contenido || "";
      document.getElementById("notepad-date-lbl").textContent = data.fecha || "";
    } catch {
      // Offline fallback
    }
  }

  async function guardarNotaActual() {
    const contenido = textarea.value;
    try {
      await fetch(`/api/notas/${paginaActualNotas}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ contenido }),
      });
    } catch {
      // Ignorar error transitorio
    }
  }
}

// =========================================================================
// 3. PUNTO DE VENTA (Carrito y Búsqueda Interactiva)
// =========================================================================
function inicializarPuntoVenta() {
  const contenedorVenta = document.getElementById("pos-container");
  if (!contenedorVenta) return;

  let carrito = [];
  let productoBusquedaSeleccionado = null;

  // Toggle de modo de búsqueda
  const btnModoNombre = document.getElementById("btn-modo-nombre");
  const btnModoCodigo = document.getElementById("btn-modo-codigo");
  const panelModoNombre = document.getElementById("panel-modo-nombre");
  const panelModoCodigo = document.getElementById("panel-modo-codigo");
  const inputBusquedaNombre = document.getElementById("input-busqueda-nombre");
  const inputCodigo = document.getElementById("input-codigo");

  if (btnModoNombre && btnModoCodigo) {
    btnModoNombre.addEventListener("click", () => {
      btnModoNombre.classList.add("active");
      btnModoCodigo.classList.remove("active");
      panelModoNombre.style.display = "block";
      panelModoCodigo.style.display = "none";
      inputBusquedaNombre.focus();
    });

    btnModoCodigo.addEventListener("click", () => {
      btnModoCodigo.classList.add("active");
      btnModoNombre.classList.remove("active");
      panelModoNombre.style.display = "none";
      panelModoCodigo.style.display = "block";
      inputCodigo.focus();
    });
  }

  const tbodyBusqueda = document.getElementById("tbody-busqueda");
  if (tbodyBusqueda) {
    // Si ya hay filas al cargar la página (renderizadas por Jinja), seleccionar la primera
    const primeraFila = tbodyBusqueda.querySelector("tr[data-producto]");
    if (primeraFila) {
      try {
        productoBusquedaSeleccionado = JSON.parse(primeraFila.dataset.producto);
        primeraFila.classList.add("selected");
      } catch (err) {}
    }

    // Navegar productos de venta con las flechas arriba/abajo desde el campo de búsqueda.
    if (inputBusquedaNombre) {
      inputBusquedaNombre.addEventListener("keydown", (e) => {
        if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
        const filas = Array.from(tbodyBusqueda.querySelectorAll("tr[data-producto]"));
        if (filas.length === 0) return;

        const actual = filas.indexOf(tbodyBusqueda.querySelector("tr.selected"));
        const siguiente = actual < 0
          ? 0
          : Math.max(0, Math.min(filas.length - 1, actual + (e.key === "ArrowDown" ? 1 : -1)));

        e.preventDefault();
        filas.forEach(fila => fila.classList.remove("selected"));
        filas[siguiente].classList.add("selected");
        try {
          productoBusquedaSeleccionado = JSON.parse(filas[siguiente].dataset.producto);
        } catch (err) {}
        filas[siguiente].scrollIntoView({ block: "nearest" });
      });
    }

    // Event delegation para Click simple: seleccionar producto
    tbodyBusqueda.addEventListener("click", (e) => {
      const tr = e.target.closest("tr[data-producto]");
      if (!tr) return;
      tbodyBusqueda.querySelectorAll("tr").forEach(r => r.classList.remove("selected"));
      tr.classList.add("selected");
      try {
        productoBusquedaSeleccionado = JSON.parse(tr.dataset.producto);
      } catch (err) {}
    });

    // Event delegation para Doble Click: agregar al carrito inmediatamente
    tbodyBusqueda.addEventListener("dblclick", (e) => {
      const tr = e.target.closest("tr[data-producto]");
      if (!tr) return;
      tbodyBusqueda.querySelectorAll("tr").forEach(r => r.classList.remove("selected"));
      tr.classList.add("selected");
      try {
        const prod = JSON.parse(tr.dataset.producto);
        productoBusquedaSeleccionado = prod;
        agregarAlCarrito(prod);
      } catch (err) {}
    });
  }

  // Búsqueda en vivo por nombre
  let debounceTimer = null;
  if (inputBusquedaNombre) {
    inputBusquedaNombre.addEventListener("input", () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        buscarProductosPorNombre(inputBusquedaNombre.value.trim());
      }, 150);
    });

    inputBusquedaNombre.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        agregarProductoSeleccionado();
      }
    });
  }

  window.limpiarBusquedaNombre = () => {
    if (inputBusquedaNombre) {
      inputBusquedaNombre.value = "";
      buscarProductosPorNombre("");
      inputBusquedaNombre.focus();
    }
  };

  async function buscarProductosPorNombre(q) {
    try {
      const res = await fetch(`/api/productos/buscar?q=${encodeURIComponent(q)}`);
      const productos = await res.json();
      renderizarResultadosBusqueda(productos);
    } catch (e) {
      console.error(e);
    }
  }

  function renderizarResultadosBusqueda(productos) {
    if (!tbodyBusqueda) return;
    tbodyBusqueda.innerHTML = "";

    if (productos.length === 0) {
      tbodyBusqueda.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-dim); padding: 16px;">No se encontraron productos coincidentes.</td></tr>`;
      productoBusquedaSeleccionado = null;
      return;
    }

    productos.forEach((p, index) => {
      const tr = document.createElement("tr");
      tr.dataset.id = p.id;
      tr.dataset.producto = JSON.stringify(p);

      let tagClass = "tag-normal";
      if (p.stock <= 0) tagClass = "tag-agotado";
      else if (p.stock <= 10) tagClass = "tag-stock_bajo";

      tr.className = tagClass;
      tr.innerHTML = `
        <td>${p.codigo_barras || "-"}</td>
        <td><strong>${p.nombre}</strong></td>
        <td>${p.categoria || "-"}</td>
        <td class="text-right">$${parseFloat(p.precio_venta || 0).toLocaleString("en-US", { minimumFractionDigits: 2 })}</td>
        <td class="text-center">${p.stock} ${p.unidad || "unidad"}</td>
      `;

      tbodyBusqueda.appendChild(tr);

      if (index === 0) {
        tr.classList.add("selected");
        productoBusquedaSeleccionado = p;
      }
    });
  }

  function agregarProductoSeleccionado() {
    if (!productoBusquedaSeleccionado) {
      const selectedRow = document.querySelector("#tbody-busqueda tr.selected") || document.querySelector("#tbody-busqueda tr[data-producto]");
      if (selectedRow && selectedRow.dataset.producto) {
        try {
          productoBusquedaSeleccionado = JSON.parse(selectedRow.dataset.producto);
        } catch (err) {}
      }
    }
    if (productoBusquedaSeleccionado) {
      agregarAlCarrito(productoBusquedaSeleccionado);
    } else {
      mostrarMensajeEstado("⚠️ Selecciona un producto de la lista primero.", "#e74c3c");
    }
  }
  window.agregarSeleccionadoBusqueda = agregarProductoSeleccionado;

  function mostrarMensajeEstado(texto, color = "#10b981") {
    const lbl = document.getElementById("lbl-estado-venta");
    if (lbl) {
      lbl.textContent = texto;
      lbl.style.color = color;
      clearTimeout(window.timerEstadoVenta);
      window.timerEstadoVenta = setTimeout(() => {
        lbl.textContent = "";
      }, 4000);
    }
  }

  // Lector de código de barras
  if (inputCodigo) {
    inputCodigo.addEventListener("keydown", async (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        await agregarPorCodigo();
      }
    });
  }

  window.agregarPorCodigo = async () => {
    const codigo = inputCodigo.value.trim();
    if (!codigo) return;
    try {
      const res = await fetch(`/api/productos/codigo/${encodeURIComponent(codigo)}`);
      const data = await res.json();
      if (data.encontrado) {
        agregarAlCarrito(data.producto);
        inputCodigo.value = "";
      } else {
        mostrarMensajeEstado(`⚠️ No se encontró ningún producto con el código: ${codigo}`, "#e74c3c");
      }
    } catch (e) {
      mostrarMensajeEstado("Error al buscar código.", "#e74c3c");
    }
  };

  // Carrito de compras
  function agregarAlCarrito(producto) {
    if (!producto) return;
    const stockDisp = producto.stock !== undefined ? parseInt(producto.stock) : 999999;
    const existente = carrito.find(item => item.producto_id === producto.id && item.producto_id !== null);

    if (existente) {
      if (existente.cantidad + 1 > stockDisp) {
        mostrarMensajeEstado(`⚠️ Stock insuficiente. Solo quedan ${stockDisp} unid. de «${producto.nombre}».`, "#e67e22");
        return;
      }
      existente.cantidad += 1;
      existente.subtotal = Math.round(existente.cantidad * existente.precio_unitario * 100) / 100;
      mostrarMensajeEstado(`✓ Se sumó 1 unidad de «${producto.nombre}».`, "#10b981");
    } else {
      if (stockDisp <= 0) {
        if (!confirm(`El producto «${producto.nombre}» está agotado (stock 0). ¿Deseas agregarlo de todos modos?`)) {
          return;
        }
      }
      const precio = parseFloat(producto.precio_venta || 0);
      carrito.push({
        producto_id: producto.id,
        nombre: producto.nombre,
        cantidad: 1,
        precio_unitario: precio,
        subtotal: precio,
        unidad: producto.unidad || "unidad",
      });
      mostrarMensajeEstado(`✓ «${producto.nombre}» agregado al carrito.`, "#10b981");
    }

    renderizarCarrito();
  }

  // Retener la selección por índice, no solo por la clase visual .selected:
  // la selección puede perderse cuando el navegador enfoca un botón.
  let indiceCarritoSeleccionado = null;

  function obtenerIndiceCarritoSeleccionado() {
    const filaSeleccionada = document.querySelector("#tbody-carrito tr.selected");
    if (filaSeleccionada) {
      const indiceFila = Number.parseInt(filaSeleccionada.dataset.index, 10);
      if (Number.isInteger(indiceFila) && carrito[indiceFila]) {
        indiceCarritoSeleccionado = indiceFila;
        return indiceFila;
      }
    }
    if (Number.isInteger(indiceCarritoSeleccionado) && carrito[indiceCarritoSeleccionado]) {
      return indiceCarritoSeleccionado;
    }
    return null;
  }

  window.cambiarCantidadCarrito = (delta) => {
    const index = obtenerIndiceCarritoSeleccionado();
    if (index === null) {
      alert("Selecciona un producto del carrito primero.");
      return;
    }
    const item = carrito[index];
    const cambio = Number(delta);
    if (!item || !Number.isFinite(cambio) || cambio === 0) return;

    if (cambio > 0) {
      const filaBusqueda = document.querySelector(`#tbody-busqueda tr[data-id=\"${item.producto_id}\"]`);
      let stockDisponible = null;
      if (filaBusqueda?.dataset.producto) {
        try {
          stockDisponible = Number(JSON.parse(filaBusqueda.dataset.producto).stock);
        } catch (e) {}
      }
      if (stockDisponible !== null && item.cantidad + 1 > stockDisponible) {
        mostrarMensajeEstado(`⚠️ Stock insuficiente. Solo quedan ${stockDisponible} unidades.`, "#e67e22");
        return;
      }
      item.cantidad += 1;
    } else if (item.cantidad > 1) {
      item.cantidad -= 1;
    } else {
      carrito.splice(index, 1);
      indiceCarritoSeleccionado = carrito.length ? Math.min(index, carrito.length - 1) : null;
      renderizarCarrito();
      return;
    }

    item.subtotal = Math.round(item.cantidad * item.precio_unitario * 100) / 100;
    indiceCarritoSeleccionado = index;
    renderizarCarrito();
  };

  window.quitarSeleccionadoCarrito = () => {
    const index = obtenerIndiceCarritoSeleccionado();
    if (index === null) {
      alert("Selecciona un producto del carrito.");
      return;
    }
    carrito.splice(index, 1);
    indiceCarritoSeleccionado = carrito.length ? Math.min(index, carrito.length - 1) : null;
    renderizarCarrito();
  };

  window.vaciarCarrito = () => {
    if (carrito.length === 0) return;
    if (confirm("¿Estás seguro de que deseas vaciar el carrito?")) {
      carrito = [];
      renderizarCarrito();
    }
  };

  function renderizarCarrito() {
    const tbody = document.getElementById("tbody-carrito");
    const lblTitulo = document.getElementById("lbl-titulo-carrito");
    const lblTotal = document.getElementById("lbl-total-venta");

    if (!tbody) return;
    tbody.innerHTML = "";

    let totalVenta = 0;
    carrito.forEach((item, index) => {
      totalVenta += item.subtotal;
      const tr = document.createElement("tr");
      tr.dataset.index = index;
      tr.innerHTML = `
        <td><strong>${item.nombre}</strong></td>
        <td class="text-center">${item.cantidad}</td>
        <td class="text-right">$${item.precio_unitario.toLocaleString("en-US", { minimumFractionDigits: 2 })}</td>
        <td class="text-right" style="color: #10b981; font-weight: bold;">$${item.subtotal.toLocaleString("en-US", { minimumFractionDigits: 2 })}</td>
      `;

      tr.addEventListener("click", () => {
        document.querySelectorAll("#tbody-carrito tr").forEach(r => r.classList.remove("selected"));
        tr.classList.add("selected");
        indiceCarritoSeleccionado = index;
      });

      tbody.appendChild(tr);
      if (index === indiceCarritoSeleccionado) {
        tr.classList.add("selected");
      }
    });

    if (lblTitulo) {
      lblTitulo.textContent = `🛒 Carrito de Compra (${carrito.length} producto${carrito.length === 1 ? "" : "s"})`;
    }
    if (lblTotal) {
      lblTotal.textContent = `$${totalVenta.toLocaleString("en-US", { minimumFractionDigits: 2 })}`;
    }
  }

  // Control de Forma de pago y cliente fiado
  const radiosPago = document.querySelectorAll("input[name='forma_pago']");
  const comboCliente = document.getElementById("combo-cliente");

  radiosPago.forEach(radio => {
    radio.addEventListener("change", () => {
      if (comboCliente) {
        if (radio.value === "fiado" && radio.checked) {
          comboCliente.disabled = false;
          comboCliente.focus();
        } else {
          comboCliente.disabled = true;
        }
      }
    });
  });

  // Modal Producto Manual ("Otros")
  const manualNombre = document.getElementById("manual-nombre");
  const manualPrecio = document.getElementById("manual-precio");
  const manualCantidad = document.getElementById("manual-cantidad");
  const modalManual = document.getElementById("modal-producto-manual");

  if (manualNombre) {
    manualNombre.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        manualPrecio.focus();
        manualPrecio.select();
      }
    });
  }

  if (manualPrecio) {
    manualPrecio.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        manualCantidad.focus();
        manualCantidad.select();
      }
    });
  }

  if (manualCantidad) {
    manualCantidad.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        window.agregarProductoManual();
      }
    });
  }

  if (modalManual) {
    modalManual.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        window.cerrarModalProductoManual();
      }
    });
  }

  window.abrirModalProductoManual = () => {
    if (modalManual) {
      modalManual.classList.add("active");
    }
    if (manualNombre) {
      manualNombre.focus();
      manualNombre.select();
    }
  };

  window.cerrarModalProductoManual = () => {
    if (modalManual) {
      modalManual.classList.remove("active");
    }
  };

  window.agregarProductoManual = () => {
    const nombre = manualNombre ? manualNombre.value.trim() : "";
    const precio = parseFloat(manualPrecio ? manualPrecio.value : 0);
    const cantidad = parseInt(manualCantidad ? manualCantidad.value : 1) || 1;

    if (!nombre) {
      alert("Ingresa el nombre o concepto del producto.");
      if (manualNombre) manualNombre.focus();
      return;
    }
    if (isNaN(precio) || precio <= 0) {
      alert("Ingresa un precio válido.");
      if (manualPrecio) manualPrecio.focus();
      return;
    }

    carrito.push({
      producto_id: null,
      nombre: nombre,
      cantidad: cantidad,
      precio_unitario: precio,
      subtotal: Math.round(precio * cantidad * 100) / 100,
      manual: true,
    });

    window.cerrarModalProductoManual();
    if (manualNombre) manualNombre.value = "";
    if (manualPrecio) manualPrecio.value = "";
    if (manualCantidad) manualCantidad.value = "1";
    renderizarCarrito();
    mostrarMensajeEstado(`✓ «${nombre}» agregado al carrito.`, "#10b981");
  };

  // Confirmar Venta con mensaje Sí / No
  window.confirmarVenta = () => {
    if (carrito.length === 0) {
      alert("El carrito está vacío. Agrega productos antes de confirmar.");
      return;
    }

    const formaPagoInput = document.querySelector("input[name='forma_pago']:checked");
    const formaPago = formaPagoInput ? formaPagoInput.value : "efectivo";

    if (formaPago === "fiado") {
      const clienteId = comboCliente.value;
      if (!clienteId) {
        alert("Debes seleccionar un cliente registrado para la venta fiada.");
        return;
      }
    }

    const total = carrito.reduce((sum, item) => sum + item.subtotal, 0);
    const etiquetaPago = formaPago === "tarjeta" ? "Transferencia" : (formaPago === "fiado" ? "Fiado" : "Efectivo");

    const modalConfirm = document.getElementById("modal-confirmar-venta");
    const lblTexto = document.getElementById("lbl-confirmar-venta-texto");
    if (lblTexto) {
      lblTexto.textContent = `¿Deseas registrar la venta por un total de $${total.toLocaleString("en-US", { minimumFractionDigits: 2 })} (${etiquetaPago})?`;
    }
    if (modalConfirm) {
      modalConfirm.classList.add("active");
      const btnSi = document.getElementById("btn-modal-si-confirmar");
      if (btnSi) btnSi.focus();
    }
  };

  window.cerrarModalConfirmarVenta = () => {
    const modalConfirm = document.getElementById("modal-confirmar-venta");
    if (modalConfirm) modalConfirm.classList.remove("active");
  };

  window.ejecutarVentaConfirmada = async () => {
    window.cerrarModalConfirmarVenta();

    const formaPagoInput = document.querySelector("input[name='forma_pago']:checked");
    const formaPago = formaPagoInput ? formaPagoInput.value : "efectivo";
    let clienteId = null;

    if (formaPago === "fiado") {
      clienteId = comboCliente.value;
    }

    try {
      const res = await fetch("/api/ventas/confirmar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          carrito: carrito,
          forma_pago: formaPago,
          cliente_id: clienteId,
        }),
      });

      const data = await res.json();
      if (data.ok) {
        // Mostrar Ticket de venta para imprimir
        mostrarTicketVenta(data.ticket);
        // Vaciar carrito
        carrito = [];
        renderizarCarrito();
        mostrarMensajeEstado(data.mensaje || "✓ Venta registrada con éxito.", "#10b981");
        // Refrescar resultados de búsqueda para actualizar stocks
        if (inputBusquedaNombre) {
          buscarProductosPorNombre(inputBusquedaNombre.value.trim());
        }
      } else {
        alert("Error al confirmar venta: " + data.mensaje);
      }
    } catch (e) {
      alert("Error en el servidor al confirmar la venta.");
    }
  };

  // Soporte teclado para cerrar modal de confirmación con Escape
  window.addEventListener("keydown", (e) => {
    const modalConfirm = document.getElementById("modal-confirmar-venta");
    if (modalConfirm && modalConfirm.classList.contains("active")) {
      if (e.key === "Escape") {
        window.cerrarModalConfirmarVenta();
      }
    }
  });

  function mostrarTicketVenta(textoTicket) {
    const modal = document.getElementById("modal-ticket");
    const pre = document.getElementById("ticket-texto-pre");
    if (!modal || !pre) return;
    pre.textContent = textoTicket;
    modal.classList.add("active");
  }

  window.cerrarModalTicket = () => {
    document.getElementById("modal-ticket").classList.remove("active");
  };

  window.imprimirTicket = () => {
    const contenido = document.getElementById("ticket-texto-pre").textContent;
    const ventana = window.open("", "_blank");
    ventana.document.write(`<pre style="font-family: monospace; font-size: 13px; line-height: 1.4;">${contenido}</pre>`);
    ventana.document.close();
    ventana.focus();
    ventana.print();
    ventana.close();
  };
}
