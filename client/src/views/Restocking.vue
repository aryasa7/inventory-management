<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.setBudget') }}</h3>
        </div>
        <div class="budget-control">
          <input
            type="range"
            v-model.number="budget"
            min="0"
            :max="maxBudget"
            step="100"
            class="budget-slider"
          />
          <div class="budget-display">{{ formatCurrency(budget, currentCurrency) }}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendedItems') }} ({{ recommendations.length }})</h3>
        </div>
        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.itemName') }}</th>
                <th>{{ t('restocking.table.category') }}</th>
                <th>{{ t('restocking.table.currentStock') }}</th>
                <th>{{ t('restocking.table.reorderPoint') }}</th>
                <th>{{ t('restocking.table.forecastedDemand') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th>{{ t('restocking.table.shortfall') }}</th>
                <th>{{ t('restocking.table.recommendedQty') }}</th>
                <th>{{ t('restocking.table.unitCost') }}</th>
                <th>{{ t('restocking.table.lineTotal') }}</th>
                <th>{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="rec in recommendations" :key="rec.sku">
                <td><strong>{{ rec.sku }}</strong></td>
                <td>{{ rec.item_name }}</td>
                <td>{{ rec.category }}</td>
                <td>{{ rec.current_quantity }}</td>
                <td>{{ rec.reorder_point }}</td>
                <td>{{ rec.forecasted_demand }}</td>
                <td>
                  <span :class="['badge', rec.trend]">
                    {{ t(`trends.${rec.trend}`) }}
                  </span>
                </td>
                <td>{{ rec.shortfall }}</td>
                <td><strong>{{ rec.recommended_quantity }}</strong></td>
                <td>{{ currencySymbol }}{{ rec.unit_cost }}</td>
                <td><strong>{{ currencySymbol }}{{ rec.line_total.toLocaleString() }}</strong></td>
                <td>{{ rec.lead_time_days }}</td>
              </tr>
            </tbody>
          </table>
          <div v-if="recommendations.length === 0" class="empty-state">
            {{ t('restocking.noRecommendations') }}
          </div>
        </div>
      </div>

      <div class="card">
        <div class="summary-row">
          <div class="summary-item">
            <div class="summary-label">{{ t('restocking.totalCost') }}</div>
            <div class="summary-value">{{ currencySymbol }}{{ totalRecommendedCost.toLocaleString() }}</div>
          </div>
          <div class="summary-item">
            <div class="summary-label">{{ t('restocking.remainingBudget') }}</div>
            <div class="summary-value">{{ currencySymbol }}{{ remainingBudget.toLocaleString() }}</div>
          </div>
          <button
            class="place-order-btn"
            :disabled="submitting || recommendations.length === 0"
            @click="placeOrder"
          >
            {{ t('restocking.placeOrder') }}
          </button>
        </div>

        <div v-if="submitSuccess" class="success-banner">
          {{ t('restocking.orderPlaced') }} — {{ submitSuccess.order_number }}
        </div>
        <div v-if="submitError" class="error">{{ submitError }}</div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrency } from '../utils/currency'

// Trend multipliers mirror the backend's urgency scoring so the slider can
// recompute recommendations instantly client-side without a round-trip per drag
const TREND_WEIGHT = { increasing: 1.5, stable: 1.0, decreasing: 0.5 }

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency } = useI18n()

    const currencySymbol = computed(() => {
      return currentCurrency.value === 'JPY' ? '¥' : '$'
    })

    const loading = ref(true)
    const error = ref(null)
    const forecasts = ref([])
    const inventoryItems = ref([])
    // sku -> lead_time_days lookup. The /api/inventory response (InventoryItem
    // model) doesn't expose lead_time_days even though it exists in the
    // underlying data, so it can't be joined in from inventoryItems directly.
    // We backfill it once from the recommendations endpoint (which reads the
    // raw item records) using a budget large enough to cover every candidate,
    // so the slider itself still recomputes everything else purely client-side.
    const leadTimeBySku = ref({})

    const budget = ref(5000)
    const maxBudget = ref(50000)

    const submitting = ref(false)
    const submitSuccess = ref(null)
    const submitError = ref(null)

    // Restocking is a whole-catalog budget optimization (not scoped to any single
    // warehouse/category/status/month), so it intentionally does not use the
    // shared useFilters() composable that drives the rest of the app's views
    const loadData = async () => {
      try {
        loading.value = true
        error.value = null
        const [forecastsData, inventoryData, leadTimeData] = await Promise.all([
          api.getDemandForecasts(),
          api.getInventory(),
          api.getRestockingRecommendations(1000000)
        ])
        forecasts.value = forecastsData
        inventoryItems.value = inventoryData

        const leadTimeMap = {}
        leadTimeData.forEach(rec => {
          leadTimeMap[rec.sku] = rec.lead_time_days
        })
        leadTimeBySku.value = leadTimeMap
      } catch (err) {
        error.value = 'Failed to load restocking data: ' + err.message
      } finally {
        loading.value = false
      }
    }

    // Join forecasts to inventory by SKU, score urgency, and sort descending
    const candidates = computed(() => {
      const inventoryBySku = {}
      inventoryItems.value.forEach(item => {
        inventoryBySku[item.sku] = item
      })

      const list = []
      forecasts.value.forEach(forecast => {
        const item = inventoryBySku[forecast.item_sku]
        if (!item) return

        const shortfall = Math.max(
          forecast.forecasted_demand - item.quantity_on_hand,
          item.reorder_point - item.quantity_on_hand,
          0
        )
        if (shortfall <= 0) return

        const weight = TREND_WEIGHT[forecast.trend] ?? 1.0
        const urgencyScore = (shortfall / Math.max(item.reorder_point, 1)) * weight

        list.push({
          sku: item.sku,
          item_name: item.name,
          category: item.category,
          warehouse: item.warehouse,
          current_quantity: item.quantity_on_hand,
          reorder_point: item.reorder_point,
          forecasted_demand: forecast.forecasted_demand,
          trend: forecast.trend,
          shortfall,
          urgency_score: urgencyScore,
          unit_cost: item.unit_cost,
          lead_time_days: leadTimeBySku.value[item.sku]
        })
      })

      list.sort((a, b) => b.urgency_score - a.urgency_score)
      return list
    })

    // Greedily allocate the budget across candidates in urgency order
    const recommendations = computed(() => {
      let remaining = budget.value
      const result = []

      for (const c of candidates.value) {
        if (remaining <= 0) break
        const affordableUnits = Math.floor(remaining / c.unit_cost)
        const qty = Math.min(c.shortfall, affordableUnits)
        if (qty <= 0) continue

        const lineTotal = Math.round(qty * c.unit_cost * 100) / 100
        remaining -= lineTotal

        result.push({
          ...c,
          recommended_quantity: qty,
          line_total: lineTotal
        })
      }

      return result
    })

    const totalRecommendedCost = computed(() => {
      return recommendations.value.reduce((sum, r) => sum + r.line_total, 0)
    })

    const remainingBudget = computed(() => {
      return Math.max(budget.value - totalRecommendedCost.value, 0)
    })

    const placeOrder = async () => {
      submitting.value = true
      submitSuccess.value = null
      submitError.value = null
      try {
        const payload = {
          budget: budget.value,
          items: recommendations.value.map(r => ({
            sku: r.sku,
            item_name: r.item_name,
            quantity: r.recommended_quantity,
            unit_cost: r.unit_cost,
            line_total: r.line_total,
            lead_time_days: r.lead_time_days
          }))
        }
        submitSuccess.value = await api.createRestockingOrder(payload)
      } catch (err) {
        submitError.value = 'Failed to place order: ' + err.message
      } finally {
        submitting.value = false
      }
    }

    onMounted(() => loadData())

    return {
      t,
      currentCurrency,
      currencySymbol,
      formatCurrency,
      loading,
      error,
      budget,
      maxBudget,
      recommendations,
      totalRecommendedCost,
      remainingBudget,
      submitting,
      submitSuccess,
      submitError,
      placeOrder
    }
  }
}
</script>

<style scoped>
.budget-control {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
  padding: 1rem 0;
}

.budget-slider {
  width: 100%;
  max-width: 600px;
  -webkit-appearance: none;
  appearance: none;
  height: 6px;
  border-radius: 6px;
  background: #e2e8f0;
  outline: none;
  cursor: pointer;
}

.budget-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #3b82f6;
  border: 2px solid white;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
  cursor: pointer;
  transition: all 0.2s;
}

.budget-slider::-webkit-slider-thumb:hover {
  background: #2563eb;
  box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.15);
}

.budget-slider::-moz-range-thumb {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #3b82f6;
  border: 2px solid white;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
  cursor: pointer;
  transition: all 0.2s;
}

.budget-slider::-moz-range-thumb:hover {
  background: #2563eb;
  box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.15);
}

.budget-slider::-moz-range-track {
  height: 6px;
  border-radius: 6px;
  background: #e2e8f0;
}

.budget-display {
  font-size: 2rem;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.025em;
}

.empty-state {
  text-align: center;
  padding: 2rem;
  color: #64748b;
  font-size: 0.938rem;
}

.summary-row {
  display: flex;
  align-items: center;
  gap: 2rem;
}

.summary-item {
  flex: 1;
}

.summary-label {
  color: #64748b;
  font-size: 0.875rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 0.375rem;
}

.summary-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
}

.place-order-btn {
  padding: 0.75rem 1.75rem;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 0.938rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  flex-shrink: 0;
}

.place-order-btn:hover:not(:disabled) {
  background: #2563eb;
}

.place-order-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.success-banner {
  margin-top: 1rem;
  padding: 1rem;
  background: #d1fae5;
  border: 1px solid #a7f3d0;
  color: #065f46;
  border-radius: 8px;
  font-size: 0.938rem;
  font-weight: 500;
}
</style>
