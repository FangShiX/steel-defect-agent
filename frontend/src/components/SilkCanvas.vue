<template>
  <div ref="containerRef" class="silk-canvas"></div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as THREE from 'three'

const props = defineProps({
  speed: { type: Number, default: 5 },
  scale: { type: Number, default: 1 },
  color: { type: String, default: '#7B7481' },
  noiseIntensity: { type: Number, default: 1.5 },
  rotation: { type: Number, default: 0 },
})

const containerRef = ref(null)

let renderer, scene, camera, mesh, animationId
let lastTime = 0

const disposeScene = () => {
  cancelAnimationFrame(animationId)
  if (mesh) {
    mesh.geometry.dispose()
    mesh.material.dispose()
    mesh = null
  }
  if (renderer) {
    renderer.dispose()
    renderer = null
  }
  scene = null
  camera = null
  lastTime = 0
}

const hexToNormalizedRGB = (hex) => {
  hex = hex.replace('#', '')
  return [
    parseInt(hex.slice(0, 2), 16) / 255,
    parseInt(hex.slice(2, 4), 16) / 255,
    parseInt(hex.slice(4, 6), 16) / 255,
  ]
}

const vertexShader = /* glsl */ `
varying vec2 vUv;
varying vec3 vPosition;

void main() {
  vPosition = position;
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`

const fragmentShader = /* glsl */ `
varying vec2 vUv;
varying vec3 vPosition;

uniform float uTime;
uniform vec3  uColor;
uniform float uSpeed;
uniform float uScale;
uniform float uRotation;
uniform float uNoiseIntensity;

const float e = 2.71828182845904523536;

float noise(vec2 texCoord) {
  float G = e;
  vec2  r = (G * sin(G * texCoord));
  return fract(r.x * r.y * (1.0 + texCoord.x));
}

vec2 rotateUvs(vec2 uv, float angle) {
  float c = cos(angle);
  float s = sin(angle);
  mat2  rot = mat2(c, -s, s, c);
  return rot * uv;
}

void main() {
  float rnd        = noise(gl_FragCoord.xy);
  vec2  uv         = rotateUvs(vUv * uScale, uRotation);
  float tOffset    = uSpeed * uTime;

  uv.y += 0.03 * sin(8.0 * uv.x - tOffset);

  float pattern = 0.6 +
                  0.4 * sin(5.0 * (uv.x + uv.y +
                                   cos(3.0 * uv.x + 5.0 * uv.y) +
                                   0.02 * tOffset) +
                           sin(20.0 * (uv.x + uv.y - 0.1 * tOffset)));

  vec4 col = vec4(uColor, 1.0) * vec4(pattern) - rnd / 15.0 * uNoiseIntensity;
  col.a = 1.0;
  gl_FragColor = col;
}
`

const createShaderMaterial = () => {
  const [r, g, b] = hexToNormalizedRGB(props.color)
  return new THREE.ShaderMaterial({
    vertexShader,
    fragmentShader,
    uniforms: {
      uTime: { value: 0 },
      uColor: { value: new THREE.Color(r, g, b) },
      uSpeed: { value: props.speed },
      uScale: { value: props.scale },
      uRotation: { value: props.rotation },
      uNoiseIntensity: { value: props.noiseIntensity },
    },
    depthWrite: false,
  })
}

const updateUniforms = () => {
  if (!mesh) return
  const [r, g, b] = hexToNormalizedRGB(props.color)
  mesh.material.uniforms.uColor.value.setRGB(r, g, b)
  mesh.material.uniforms.uSpeed.value = props.speed
  mesh.material.uniforms.uScale.value = props.scale
  mesh.material.uniforms.uRotation.value = props.rotation
  mesh.material.uniforms.uNoiseIntensity.value = props.noiseIntensity
}

const resize = () => {
  if (!containerRef.value) return
  const { width, height } = containerRef.value.getBoundingClientRect()
  if (renderer) {
    renderer.setSize(width, height)
  }
  if (camera) {
    camera.aspect = width / Math.max(height, 1)
    camera.updateProjectionMatrix()
  }
  if (mesh) {
    mesh.scale.set(width, height, 1)
  }
}

const animate = () => {
  animationId = requestAnimationFrame(animate)
  const now = performance.now() / 1000
  if (lastTime === 0) lastTime = now
  const delta = now - lastTime
  lastTime = now
  if (mesh) {
    mesh.material.uniforms.uTime.value += 0.1 * delta
  }
  if (renderer) renderer.render(scene, camera)
}

onMounted(() => {
  const el = containerRef.value
  if (!el) return

  try {
    const { width, height } = el.getBoundingClientRect()

    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setSize(width, height)

    scene = new THREE.Scene()
    camera = new THREE.OrthographicCamera(
      width / -2, width / 2,
      height / 2, height / -2,
      0.1, 10
    )
    camera.position.z = 1

    const geometry = new THREE.PlaneGeometry(1, 1)
    const material = createShaderMaterial()
    mesh = new THREE.Mesh(geometry, material)
    mesh.scale.set(width, height, 1)
    scene.add(mesh)

    el.appendChild(renderer.domElement)

    window.addEventListener('resize', resize)
    lastTime = 0
    animate()
  } catch {
    // The login form must remain usable on browsers without WebGL support.
    disposeScene()
  }
})

onUnmounted(() => {
  window.removeEventListener('resize', resize)
  disposeScene()
})

watch(() => [props.color, props.speed, props.scale, props.rotation, props.noiseIntensity], updateUniforms)
</script>

<style lang="scss" scoped>
.silk-canvas {
  width: 100%;
  height: 100%;
  position: absolute;
  inset: 0;
  overflow: hidden;
  background: #1f1f1f;

  canvas {
    display: block;
  }
}
</style>
