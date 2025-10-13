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
        lengthMenu: [
            [10, 25, 50, 100, 300, 500, -1],
            ['10', '25', '50', '100', '300', '500', 'Todos'],
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
    const autoSubmitControls = document.querySelectorAll('[data-auto-submit="true"]');
    autoSubmitControls.forEach((control) => {
        control.addEventListener('change', () => {
            if (control.disabled) {
                return;
            }
            const form = control.form || control.closest('form');
            if (form) {
                form.requestSubmit ? form.requestSubmit() : form.submit();
            }
        });
    });
});

document.addEventListener('DOMContentLoaded', () => {
    const terminalHiddenInput = document.getElementById('terminal');
    const terminalSelect = document.getElementById('terminal-select');
    const customWrapper = document.querySelector('.terminal-custom');
    const customInput = document.getElementById('terminal-custom');
    const progressOverlay = document.getElementById('progress-overlay');
    const backToTopBtn = document.querySelector('.back-to-top');

    if (terminalHiddenInput && terminalSelect) {
        const controlForm = terminalHiddenInput.form || document.getElementById('controlTabsForm');
        const specialValues = (terminalSelect.dataset.specialValues || '')
            .split(',')
            .map((value) => value.trim())
            .filter((value) => value.length > 0);
        let initializingSelect = true;
        let autoSubmitButton = null;

        const ensureAutoSubmitButton = (actionValue) => {
            if (!controlForm) {
                return null;
            }
            if (!autoSubmitButton) {
                autoSubmitButton = document.createElement('button');
                autoSubmitButton.type = 'submit';
                autoSubmitButton.name = 'action';
                autoSubmitButton.hidden = true;
                autoSubmitButton.dataset.autoAction = 'true';
                controlForm.appendChild(autoSubmitButton);
            }
            autoSubmitButton.value = actionValue;
            return autoSubmitButton;
        };

        const submitFormWithAction = (actionValue) => {
            if (!controlForm) {
                return;
            }
            const submitter = ensureAutoSubmitButton(actionValue);
            if (controlForm.requestSubmit && submitter) {
                controlForm.requestSubmit(submitter);
                return;
            }
            const tempInput = document.createElement('input');
            tempInput.type = 'hidden';
            tempInput.name = 'action';
            tempInput.value = actionValue;
            controlForm.appendChild(tempInput);
            controlForm.submit();
            controlForm.removeChild(tempInput);
        };

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

            if (specialValues.includes(selectedValue) && !initializingSelect) {
                submitFormWithAction('fetch');
            }

            if (initializingSelect) {
                initializingSelect = false;
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
    }

    const progressForms = document.querySelectorAll('form[data-progress-form="true"]');
    const longRunningActions = new Set([
        'fetch',
        'push',
        'delete',
        'import',
        'status',
        'export_excel',
        'export_csv',
        'export_json',
    ]);

    const progressBar = progressOverlay ? progressOverlay.querySelector('[data-progress-bar]') : null;
    const progressText = progressOverlay ? progressOverlay.querySelector('[data-progress-text]') : null;
    const progressSubtext = progressOverlay ? progressOverlay.querySelector('[data-progress-subtext]') : null;
    const progressCount = progressOverlay ? progressOverlay.querySelector('[data-progress-count]') : null;

    let progressAnimationFrame = null;
    let progressStartTime = null;
    let progressTotal = 0;
    let progressEstimatedDuration = 0;
    let progressPerItem = 0;

    const progressDescriptions = {
        fetch: 'Cargando empleados del terminal…',
        push: 'Enviando empleados seleccionados…',
        delete: 'Eliminando empleados seleccionados…',
        import: 'Importando empleados…',
        status: 'Obteniendo estado del terminal…',
        export_excel: 'Generando exportación en Excel…',
        export_csv: 'Generando exportación en CSV…',
        export_json: 'Generando exportación en JSON…',
    };

    const progressTiming = {
        fetch: { base: 1200, perItem: 80 },
        push: { base: 800, perItem: 180 },
        delete: { base: 600, perItem: 160 },
        import: { base: 700, perItem: 120 },
        status: { base: 800, perItem: 0 },
        export_excel: { base: 900, perItem: 100 },
        export_csv: { base: 700, perItem: 80 },
        export_json: { base: 600, perItem: 60 },
    };

    const calculateAffected = (action, form) => {
        const employeesForm = document.getElementById('employees-form');
        const selectedCount = employeesForm
            ? employeesForm.querySelectorAll('tbody input[type="checkbox"]:checked').length
            : 0;
        const totalCheckboxes = employeesForm
            ? employeesForm.querySelectorAll('tbody input[type="checkbox"]').length
            : 0;
        if (['push', 'delete', 'export_excel', 'export_csv', 'export_json'].includes(action)) {
            return selectedCount > 0 ? selectedCount : totalCheckboxes || 1;
        }
        if (action === 'fetch') {
            const selectionInfo = document.getElementById('selection-info');
            if (selectionInfo && selectionInfo.dataset.total) {
                const total = parseInt(selectionInfo.dataset.total, 10);
                if (!Number.isNaN(total) && total > 0) {
                    return total;
                }
            }
            return totalCheckboxes || 25;
        }
        if (action === 'status') {
            return 1;
        }
        if (action === 'import') {
            const fileInput = form.querySelector('input[type="file"]');
            if (fileInput && fileInput.files.length) {
                const estimated = Math.ceil(fileInput.files[0].size / 2048);
                return Math.min(Math.max(estimated, 20), 500);
            }
            return 50;
        }
        return 0;
    };

    const stopProgressAnimation = () => {
        if (progressAnimationFrame !== null) {
            cancelAnimationFrame(progressAnimationFrame);
            progressAnimationFrame = null;
        }
        progressStartTime = null;
    };

    const startProgress = (action, total) => {
        if (!progressOverlay || !progressBar) {
            return;
        }

        stopProgressAnimation();

        progressOverlay.classList.remove('d-none');
        progressOverlay.setAttribute('aria-hidden', 'false');
        progressBar.style.width = '0%';
        progressBar.setAttribute('aria-valuenow', '0');

        if (progressText) {
            progressText.textContent = progressDescriptions[action] || 'Procesando solicitud…';
        }
        if (progressSubtext) {
            progressSubtext.textContent = 'Esta operación puede tardar unos segundos.';
        }
        if (progressCount) {
            progressCount.textContent = total > 0 ? `0 de ${total} empleados` : '';
        }

        const timing = progressTiming[action] || { base: 900, perItem: 120 };
        progressPerItem = timing.perItem;
        progressTotal = total;
        progressEstimatedDuration = timing.base + (total > 0 ? timing.perItem * total : 1000);
        progressEstimatedDuration = Math.min(Math.max(progressEstimatedDuration, 800), 12000);
        progressStartTime = performance.now();

        const animate = () => {
            if (!progressStartTime) {
                return;
            }
            const elapsed = performance.now() - progressStartTime;
            const ratio = progressEstimatedDuration > 0 ? elapsed / progressEstimatedDuration : 0;
            const percent = Math.min(98, ratio * 100);
            progressBar.style.width = `${percent}%`;
            progressBar.setAttribute('aria-valuenow', String(Math.round(percent)));

            if (progressCount && total > 0) {
                let processedEmployees = Math.floor(elapsed / Math.max(progressPerItem, 80));
                processedEmployees = Math.min(total - 1, processedEmployees);
                if (elapsed > progressEstimatedDuration * 0.9) {
                    processedEmployees = Math.max(processedEmployees, total - 1);
                }
                processedEmployees = Math.max(0, processedEmployees);
                progressCount.textContent = `${processedEmployees} de ${total} empleados`;
            }

            if (elapsed < progressEstimatedDuration) {
                progressAnimationFrame = requestAnimationFrame(animate);
            }
        };

        progressAnimationFrame = requestAnimationFrame(animate);
    };

    const finishProgress = () => {
        stopProgressAnimation();
        if (!progressOverlay || !progressBar) {
            return;
        }
        progressBar.style.width = '100%';
        progressBar.setAttribute('aria-valuenow', '100');
        if (progressCount && progressCount.textContent) {
            const text = progressCount.textContent;
            if (!text.startsWith('Completado')) {
                progressCount.textContent = `Completado (${text})`;
            }
        }
        progressOverlay.setAttribute('aria-hidden', 'true');
    };

    window.addEventListener('beforeunload', () => {
        finishProgress();
    });

    progressForms.forEach((form) => {
        form.addEventListener('submit', (event) => {
            const submitter = event.submitter;
            if (!submitter || submitter.name !== 'action') {
                return;
            }
            const actionValue = submitter.value;
            if (longRunningActions.has(actionValue) && progressOverlay) {
                const total = calculateAffected(actionValue, form) || 0;
                startProgress(actionValue, total);
            }
        });
    });

    if (backToTopBtn) {
        const toggleBackToTop = () => {
            if (window.scrollY > 250) {
                backToTopBtn.classList.remove('d-none');
            } else {
                backToTopBtn.classList.add('d-none');
            }
        };

        window.addEventListener('scroll', toggleBackToTop, { passive: true });
        backToTopBtn.addEventListener('click', () => {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        });

        toggleBackToTop();
    }
});
