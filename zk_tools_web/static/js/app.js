document.addEventListener('DOMContentLoaded', () => {
    const selectionInfo = document.getElementById('selection-info');
    const tableElement = document.getElementById('employees-table');

    if (!tableElement) {
        if (selectionInfo) {
            selectionInfo.dataset.total = '0';
            selectionInfo.dataset.selected = '0';
            selectionInfo.textContent = 'Seleccionados: 0 de 0';
        }
        return;
    }

    const $table = $('#employees-table');
    $table.DataTable({
        pageLength: 25,
        order: [[1, 'asc']],
        autoWidth: false,
        columnDefs: [
            { orderable: false, targets: 0 },
        ],
        language: {
            decimal: ',',
            thousands: '.',
            emptyTable: 'Sin datos disponibles en la tabla',
            info: 'Mostrando _START_ a _END_ de _TOTAL_ empleados',
            infoEmpty: 'Mostrando 0 a 0 de 0 empleados',
            infoFiltered: '(filtrado de _MAX_ registros totales)',
            lengthMenu: 'Mostrar _MENU_ registros',
            loadingRecords: 'Cargando...',
            processing: 'Procesando...',
            search: 'Buscar:',
            zeroRecords: 'No se encontraron coincidencias',
            paginate: {
                first: 'Primero',
                last: 'Último',
                next: 'Siguiente',
                previous: 'Anterior',
            },
        },
        dom: '<"row mb-3"<"col-sm-12 col-md-6"l><"col-sm-12 col-md-6 text-md-end"f>>tip',
    });

    const getAllCheckboxes = () => $table.find('tbody input[type="checkbox"]');

    const updateSelectionInfo = () => {
        if (!selectionInfo) {
            return;
        }
        const selectedCount = getAllCheckboxes().filter(':checked').length;
        const totalEmployees = selectionInfo.dataset.total
            ? parseInt(selectionInfo.dataset.total, 10)
            : getAllCheckboxes().length;
        selectionInfo.dataset.selected = String(selectedCount);
        selectionInfo.textContent = `Seleccionados: ${selectedCount} de ${totalEmployees}`;
    };

    const updateRowClasses = () => {
        getAllCheckboxes().each(function eachRow() {
            const $row = $(this).closest('tr');
            $row.toggleClass('selected-row', this.checked);
        });
    };

    let lastClicked = null;

    $table.on('change', 'tbody input[type="checkbox"]', () => {
        updateRowClasses();
        updateSelectionInfo();
    });

    $table.on('click', 'tbody input[type="checkbox"]', function handleClick(event) {
        const checkboxList = getAllCheckboxes().toArray();
        if (event.shiftKey && lastClicked && lastClicked !== this) {
            const currentIndex = checkboxList.indexOf(this);
            const lastIndex = checkboxList.indexOf(lastClicked);
            if (currentIndex !== -1 && lastIndex !== -1) {
                const start = Math.min(currentIndex, lastIndex);
                const end = Math.max(currentIndex, lastIndex);
                const shouldCheck = this.checked;
                for (let i = start; i <= end; i += 1) {
                    checkboxList[i].checked = shouldCheck;
                }
                updateRowClasses();
                updateSelectionInfo();
            }
        }
        lastClicked = this;
    });

    $table.on('draw.dt', () => {
        updateRowClasses();
    });

    updateRowClasses();
    updateSelectionInfo();
});

document.addEventListener('DOMContentLoaded', () => {
    const terminalHiddenInput = document.getElementById('terminal');
    const terminalSelect = document.getElementById('terminal-select');
    const customWrapper = document.querySelector('.terminal-custom');
    const customInput = document.getElementById('terminal-custom');

    if (!terminalHiddenInput || !terminalSelect) {
        return;
    }

    const showCustom = () => {
        if (customWrapper) {
            customWrapper.classList.remove('d-none');
        }
        if (customInput) {
            customInput.focus();
        }
    };

    const hideCustom = () => {
        if (customWrapper) {
            customWrapper.classList.add('d-none');
        }
    };

    const syncHidden = (value) => {
        terminalHiddenInput.value = value.trim();
    };

    const handleSelectChange = () => {
        const selectedValue = terminalSelect.value;
        if (selectedValue === '__custom__') {
            showCustom();
            if (customInput) {
                syncHidden(customInput.value);
            } else {
                syncHidden('');
            }
        } else {
            hideCustom();
            syncHidden(selectedValue);
        }
    };

    terminalSelect.addEventListener('change', handleSelectChange);

    if (customInput) {
        customInput.addEventListener('input', () => {
            if (terminalSelect.value !== '__custom__') {
                terminalSelect.value = '__custom__';
                showCustom();
            }
            syncHidden(customInput.value);
        });
    }

    handleSelectChange();
});
