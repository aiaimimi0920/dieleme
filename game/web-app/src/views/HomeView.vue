<script setup>
import { ref, computed, onMounted } from 'vue'
import { useGameState } from '../composables/useGameState.js'

const { userData, initUserData, navigate } = useGameState()

const meta = ref(null)
const cities = ref([])
const districts = ref([])
const communities = ref([])

const selectedCity = ref(null)
const selectedDistrict = ref(null)
const selectedCommunity = ref('')
const inputBuyPrice = ref('')
const inputArea = ref('')

const loading = ref(false)
const error = ref('')
const step = ref(1) // 1: city, 2: district, 3: community+price

onMounted(async () => {
  try {
    const res = await fetch('/data/meta.json')
    meta.value = await res.json()
    cities.value = meta.value.cities
  } catch (e) {
    error.value = '数据加载失败'
  }
})

const selectCity = async (city) => {
  selectedCity.value = city
  loading.value = true
  try {
    const res = await fetch(`/data/cities/${city.id}.json`)
    const data = await res.json()
    districts.value = data.districts
    step.value = 2
  } catch (e) {
    error.value = '城市数据加载失败'
  }
  loading.value = false
}

const selectDistrict = async (district) => {
  selectedDistrict.value = district
  loading.value = true
  try {
    const res = await fetch(`/data/districts/${selectedCity.value.id}_${district.id}.json`)
    const data = await res.json()
    communities.value = Object.keys(data.communities).map(name => ({
      name,
      ...data.communities[name]
    }))
    step.value = 3
  } catch (e) {
    error.value = '区县数据加载失败'
  }
  loading.value = false
}

const canStart = computed(() => {
  return selectedCommunity.value && Number(inputBuyPrice.value) > 0 && Number(inputArea.value) > 0
})

const startGame = () => {
  const comm = communities.value.find(c => c.name === selectedCommunity.value)
  if (!comm) return

  initUserData({
    cityId: selectedCity.value.id,
    cityName: selectedCity.value.name,
    districtId: selectedDistrict.value.id,
    districtName: selectedDistrict.value.name,
    communityName: selectedCommunity.value,
    buyPrice: Number(inputBuyPrice.value),
    area: Number(inputArea.value),
    currentPrice: comm.avg_price,
    maxPrice: comm.max_price,
    trendFactor: comm.trend_factor || -0.1,
  })

  navigate('candle')
}

const goBack = () => {
  if (step.value > 1) {
    step.value--
    if (step.value === 1) {
      selectedCity.value = null
      districts.value = []
    }
    if (step.value === 2) {
      selectedDistrict.value = null
      communities.value = []
    }
  }
}
</script>

<template>
  <div class="px-5 py-8 min-h-[100dvh] flex flex-col">
    <!-- 标题区 -->
    <div class="text-center mb-8 fade-up">
      <div class="text-5xl mb-3">🏠</div>
      <h1 class="text-3xl font-black tracking-tight" style="line-height: 1.2;">
        你的<span style="color:var(--color-primary)">房</span><br>还值多少？
      </h1>
    </div>

    <!-- 全局数据概览 -->
    <div v-if="meta" class="card text-center mb-6 fade-up-delay">
      <div class="text-xs" style="color:var(--color-muted)">已收录全国法拍数据</div>
      <div class="text-2xl font-bold mt-1 num-highlight">
        {{ meta.total_communities.toLocaleString() }} <span class="text-sm font-normal" style="color:var(--color-muted)">个小区</span>
      </div>
      <div class="text-xs mt-1" style="color:var(--color-muted)">
        更新于 {{ meta.last_updated }}
      </div>
    </div>

    <!-- 步骤指示 -->
    <div class="flex items-center justify-center gap-2 mb-6 fade-up-delay">
      <div v-for="i in 3" :key="i" 
        class="w-8 h-1 rounded-full transition-all duration-300"
        :style="{ background: i <= step ? 'var(--color-primary)' : 'rgba(255,255,255,.1)' }"
      ></div>
    </div>

    <!-- 返回按钮 -->
    <button v-if="step > 1" @click="goBack" class="flex items-center gap-1 text-sm mb-4 opacity-50 hover:opacity-100 transition bg-transparent border-0 cursor-pointer" style="color:var(--color-text)">
      ← 返回
    </button>

    <!-- Step 1: 选择城市 -->
    <div v-if="step === 1" class="flex-1">
      <h2 class="text-lg font-semibold mb-4">选择您的城市</h2>
      <div class="grid grid-cols-2 gap-3">
        <button
          v-for="city in cities" :key="city.id"
          @click="selectCity(city)"
          class="card text-center py-4 cursor-pointer hover:border-[var(--color-primary)] transition-all border border-transparent"
          :class="{ 'shake': loading }"
        >
          <div class="text-lg font-semibold">{{ city.name }}</div>
        </button>
      </div>
    </div>

    <!-- Step 2: 选择区县 -->
    <div v-else-if="step === 2" class="flex-1">
      <h2 class="text-lg font-semibold mb-1">{{ selectedCity.name }}</h2>
      <p class="text-sm mb-4" style="color:var(--color-muted)">选择您的区县</p>
      <div class="grid grid-cols-2 gap-3">
        <button
          v-for="d in districts" :key="d.id"
          @click="selectDistrict(d)"
          class="card text-center py-4 cursor-pointer hover:border-[var(--color-primary)] transition-all border border-transparent"
        >
          <div class="font-medium">{{ d.name }}</div>
        </button>
      </div>
    </div>

    <!-- Step 3: 选择小区 + 输入价格 -->
    <div v-else-if="step === 3" class="flex-1 flex flex-col">
      <h2 class="text-lg font-semibold mb-1">
        {{ selectedCity.name }} · {{ selectedDistrict.name }}
      </h2>
      <p class="text-sm mb-5" style="color:var(--color-muted)">输入您的房产信息</p>

      <div class="space-y-4 flex-1">
        <div>
          <label class="block text-sm mb-2 font-medium">小区名称</label>
          <select v-model="selectedCommunity" class="select-field">
            <option value="" disabled>请选择小区</option>
            <option v-for="c in communities" :key="c.name" :value="c.name">
              {{ c.name }}
            </option>
          </select>
        </div>

        <div>
          <label class="block text-sm mb-2 font-medium">您的购入单价 <span style="color:var(--color-muted)">(元/m²)</span></label>
          <input v-model="inputBuyPrice" type="number" class="input-field" placeholder="例如: 50000">
        </div>

        <div>
          <label class="block text-sm mb-2 font-medium">建筑面积 <span style="color:var(--color-muted)">(m²)</span></label>
          <input v-model="inputArea" type="number" class="input-field" placeholder="例如: 89">
        </div>
      </div>

      <button
        :disabled="!canStart"
        @click="startGame"
        class="btn-primary mt-6"
        :style="{ opacity: canStart ? 1 : 0.4 }"
      >
        准备好面对真相了吗？
      </button>
    </div>

    <!-- 错误提示 -->
    <div v-if="error" class="text-center text-sm mt-4" style="color:var(--color-primary)">{{ error }}</div>

    <!-- 底部 -->
    <div class="text-center text-xs mt-8" style="color:var(--color-muted)">
      公益项目 · 数据来源：司法拍卖公开信息
    </div>
  </div>
</template>
