<template>
  <header class="module-header">
    <div>
      <h1 v-if="title" class="module-header__title">{{ title }}</h1>
      <p v-if="description" class="module-header__desc">{{ description }}</p>
    </div>
    <div class="module-header__actions">
      <slot />
    </div>
  </header>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  description: { type: String, default: "" },
});
</script>

<style lang="scss" scoped>
.module-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.module-header__title {
  margin: 0;
  font-size: 40px;
  font-weight: 600;
  color: #000000;
  letter-spacing: -0.3px;
}

.module-header__desc {
  margin: 4px 0 0;
  max-width: 640px;
  color: #98a2b3;
  font-size: 13px;
  line-height: 1.5;
}

.module-header__actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

@media (max-width: 780px) {
  .module-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .module-header__actions {
    justify-content: flex-start;
  }
}
</style>
