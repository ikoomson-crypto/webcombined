// Global variables
let currentProjectId = null;
let implRows = [];
let swRows = [];
let logRows = [];

let implMarkup = 0;
let swMarkup = 0;
let logMarkup = 0;
let maintMarkup = 0;

let displayCurrencyCode = 'USD';
let displayCurrencySymbol = '$';
let exchangeRate = 1;

const currencySymbols = {
    'USD': '$', 'EUR': '€', 'GBP': '£', 'GHS': '₵', 'NGN': '₦',
    'ZAR': 'R', 'CAD': '$', 'AUD': '$', 'JPY': '¥', 'CNY': '¥',
    'INR': '₹', 'CHF': 'Fr', 'SGD': 'S$', 'HKD': 'HK$', 'NZD': 'NZ$',
    'KRW': '₩', 'RUB': '₽', 'BRL': 'R$', 'MYR': 'RM', 'THB': '฿',
    'VND': '₫', 'IDR': 'Rp', 'PHP': '₱', 'PKR': '₨', 'BDT': '৳',
    'EGP': '£', 'TRY': '₺', 'MXN': '$', 'SEK': 'kr', 'NOK': 'kr',
    'DKK': 'kr', 'PLN': 'zł', 'CZK': 'Kč', 'HUF': 'Ft', 'ILS': '₪',
    'CLP': '$', 'PEN': 'S/', 'COP': '$', 'AED': 'د.إ', 'SAR': '﷼'
};

// Currency formatting functions
function formatUSD(value) {
    return '$' + value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatConverted(value) {
    if (displayCurrencyCode === 'JPY' || displayCurrencyCode === 'KRW' || displayCurrencyCode === 'VND' || displayCurrencyCode === 'IDR') {
        return displayCurrencySymbol + Math.round(value).toLocaleString();
    }
    return displayCurrencySymbol + value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function convertCurrency(value) {
    return value * exchangeRate;
}

function updateGlobalCurrency() {
    displayCurrencyCode = document.getElementById('displayCurrency')?.value || 'USD';
    displayCurrencySymbol = currencySymbols[displayCurrencyCode] || '$';
    exchangeRate = parseFloat(document.getElementById('exchangeRate')?.value) || 1;

    if (typeof renderImplTable === 'function') renderImplTable();
    if (typeof renderSwTable === 'function') renderSwTable();
    if (typeof renderLogTable === 'function') renderLogTable();
    if (typeof updateTotals === 'function') updateTotals();
}

function resetCurrency() {
    if (document.getElementById('displayCurrency')) {
        document.getElementById('displayCurrency').value = 'USD';
    }
    if (document.getElementById('exchangeRate')) {
        document.getElementById('exchangeRate').value = 1;
    }
    updateGlobalCurrency();
}

// Project currency conversion
async function convertProjectCurrency(projectId, newCurrency) {
    if (!projectId) {
        showToast('Please save the project first before converting currency.', 'warning');
        return false;
    }

    if (!confirm(`Convert this project to ${newCurrency}? All costs (consultant rates, software prices, logistics costs) will be converted using current exchange rates.`)) {
        return false;
    }

    try {
        const response = await fetch(`/api/projects/${projectId}/convert`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ currency_code: newCurrency })
        });

        const data = await response.json();
        if (data.success) {
            showToast(`Project successfully converted to ${newCurrency}`, 'success');
            if (typeof loadProject === 'function') {
                await loadProject(projectId);
            } else {
                window.location.reload();
            }
            return true;
        } else {
            showToast('Error converting currency: ' + (data.error || 'Unknown error'), 'error');
            return false;
        }
    } catch (error) {
        console.error('Error:', error);
        showToast('Error converting currency', 'error');
        return false;
    }
}

// Load exchange rates
async function loadExchangeRates() {
    try {
        const response = await fetch('/api/currencies/rates');
        const rates = await response.json();
        return rates;
    } catch (error) {
        console.error('Error loading exchange rates:', error);
        return null;
    }
}

// Get currency info
async function getCurrencyInfo(currencyCode) {
    try {
        const response = await fetch('/api/currencies');
        const currencies = await response.json();
        return currencies.find(c => c.code === currencyCode);
    } catch (error) {
        console.error('Error getting currency info:', error);
        return null;
    }
}

// Format amount in any currency
function formatCurrency(amount, currencyCode = 'USD') {
    const symbol = currencySymbols[currencyCode] || '$';
    if (currencyCode === 'JPY' || currencyCode === 'KRW' || currencyCode === 'VND' || currencyCode === 'IDR') {
        return symbol + Math.round(amount).toLocaleString();
    }
    return symbol + amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Update all displayed costs when currency changes (client-side only)
function updateDisplayCurrency(projectData, targetCurrency, exchangeRates) {
    if (!projectData || !exchangeRates) return null;

    const oldCurrency = projectData.currency_code || 'USD';
    const oldRate = exchangeRates[oldCurrency] || 1;
    const newRate = exchangeRates[targetCurrency] || 1;
    const conversionRate = newRate / oldRate;

    const convertedData = JSON.parse(JSON.stringify(projectData));

    if (convertedData.implementation_items) {
        convertedData.implementation_items.forEach(item => {
            if (item.rate) item.rate = item.rate * conversionRate;
        });
    }

    if (convertedData.software_items) {
        convertedData.software_items.forEach(item => {
            if (item.unit_price) item.unit_price = item.unit_price * conversionRate;
        });
    }

    if (convertedData.logistics_items) {
        convertedData.logistics_items.forEach(item => {
            if (item.per_diem) item.per_diem = item.per_diem * conversionRate;
            if (item.accommodation) item.accommodation = item.accommodation * conversionRate;
            if (item.transport_per_day) item.transport_per_day = item.transport_per_day * conversionRate;
            if (item.flight_cost) item.flight_cost = item.flight_cost * conversionRate;
        });
    }

    if (convertedData.annual_maintenance_cost) {
        convertedData.annual_maintenance_cost = convertedData.annual_maintenance_cost * conversionRate;
    }

    convertedData.currency_code = targetCurrency;
    convertedData.currency_symbol = currencySymbols[targetCurrency] || '$';

    return convertedData;
}

// Export functions for use in other files
window.formatCurrency = formatCurrency;
window.formatUSD = formatUSD;
window.formatConverted = formatConverted;
window.convertCurrency = convertCurrency;
window.updateGlobalCurrency = updateGlobalCurrency;
window.resetCurrency = resetCurrency;
window.convertProjectCurrency = convertProjectCurrency;
window.loadExchangeRates = loadExchangeRates;
window.getCurrencyInfo = getCurrencyInfo;
window.updateDisplayCurrency = updateDisplayCurrency;
window.currencySymbols = currencySymbols;

// Toast notification function
function showToast(message, type = 'success') {
    const container = document.getElementById('toastContainer');
    if (!container) {
        console.log(message);
        return;
    }

    const toast = document.createElement('div');
    toast.className = 'custom-toast fade-in';
    const icon = type === 'success' ? 'check-circle' :
                type === 'error' ? 'exclamation-circle' : 'info-circle';
    const color = type === 'success' ? '#27ae60' : type === 'error' ? '#e74c3c' : '#3498db';

    toast.innerHTML = `
        <div class="d-flex align-items-center">
            <i class="fas fa-${icon} me-2" style="color: ${color}"></i>
            <div class="flex-grow-1">${message}</div>
            <button class="btn-close btn-sm" onclick="this.parentElement.parentElement.remove()"></button>
        </div>
    `;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);
}

window.showToast = showToast;