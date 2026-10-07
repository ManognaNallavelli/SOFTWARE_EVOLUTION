import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  MarkerType,
  useEdgesState,
  useNodesState,
  useReactFlow,
  getNodesBounds,
  getViewportForBounds,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import { toPng } from 'html-to-image'
import '@xyflow/react/dist/style.css'
import type {
  ArchitectureGraph,
  ArchitectureNode as ArchNode,
  ArchitectureNodeKind,
} from '../../types/architecture'

const KIND_COLORS: Record<ArchitectureNodeKind, string> = {
  frontend: '#5eead4',
  backend: '#67e8f9',
  service: '#86efac',
  module: '#94a3b8',
  api: '#fbbf24',
  database: '#a5b4fc',
  external: '#fca5a5',
  config: '#cbd5e1',
  test: '#64748b',
  other: '#94a3b8',
}

const KIND_LABELS: Record<ArchitectureNodeKind, string> = {
  frontend: 'Frontend',
  backend: 'Backend',
  service: 'Service',
  module: 'Module',
  api: 'API',
  database: 'Data',
  external: 'External',
  config: 'Config',
  test: 'Test',
  other: 'Other',
}

type ArchNodeData = {
  label: string
  kind: ArchitectureNodeKind
  description?: string | null
  filePaths: string[]
  evidence: string[]
}

function ArchitectureFlowNode({ data, selected }: NodeProps) {
  const nodeData = data as ArchNodeData
  const color = KIND_COLORS[nodeData.kind] ?? KIND_COLORS.other
  const preview =
    nodeData.filePaths[0] ||
    nodeData.evidence.find((e) => e.includes('/') || e.includes('.')) ||
    nodeData.evidence[0] ||
    ''

  return (
    <div className={`arch-rf-node${selected ? ' is-selected' : ''}`} style={{ borderColor: color }}>
      <Handle type="target" position={Position.Top} className="arch-handle" />
      <span className="arch-rf-kind" style={{ color, borderColor: color }}>
        {KIND_LABELS[nodeData.kind] ?? nodeData.kind}
      </span>
      <strong className="arch-rf-title">{nodeData.label}</strong>
      {preview ? <span className="arch-rf-path">{preview}</span> : null}
      <Handle type="source" position={Position.Bottom} className="arch-handle" />
    </div>
  )
}

const nodeTypes = { architecture: ArchitectureFlowNode }

function layerOf(kind: ArchitectureNodeKind): number {
  const layers: ArchitectureNodeKind[][] = [
    ['frontend', 'backend'],
    ['api', 'service'],
    ['module', 'other', 'config'],
    ['database', 'external', 'test'],
  ]
  const idx = layers.findIndex((group) => group.includes(kind))
  return idx >= 0 ? idx : 2
}

function layoutNodes(graph: ArchitectureGraph): Node[] {
  const buckets = new Map<number, ArchNode[]>()
  for (const node of graph.nodes) {
    const layer = layerOf(node.kind)
    const list = buckets.get(layer) ?? []
    list.push(node)
    buckets.set(layer, list)
  }

  const result: Node[] = []
  const sortedLayers = [...buckets.entries()].sort((a, b) => a[0] - b[0])
  for (const [layer, items] of sortedLayers) {
    const count = items.length
    const spacingX = count > 6 ? 190 : 230
    const offsetX = Math.max(0, (920 - count * spacingX) / 2)
    items.forEach((node, index) => {
      result.push({
        id: node.id,
        type: 'architecture',
        position: {
          x: offsetX + index * spacingX,
          y: 30 + layer * 160,
        },
        data: {
          label: node.label,
          kind: node.kind,
          description: node.description,
          filePaths: node.file_paths ?? [],
          evidence: node.evidence ?? [],
        } satisfies ArchNodeData,
      })
    })
  }
  return result
}

function toFlowEdges(graph: ArchitectureGraph): Edge[] {
  return graph.edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    label: edge.label || edge.type.replace(/_/g, ' '),
    animated: edge.type === 'calls' || edge.type === 'uses' || edge.type === 'imports',
    markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: '#64748b' },
    style: { stroke: '#475569', strokeWidth: 1.35 },
    labelStyle: { fill: '#94a3b8', fontSize: 11, fontWeight: 500 },
    labelBgStyle: { fill: '#0f141c', fillOpacity: 0.92 },
    labelBgPadding: [4, 6] as [number, number],
    labelBgBorderRadius: 4,
  }))
}

type Props = {
  graph: ArchitectureGraph
  onDownloadReady?: (download: (() => Promise<void>) | null) => void
  onSelectionChange?: (node: ArchNode | null) => void
  selectedFile?: string | null
  onSelectFile?: (path: string) => void
  onAskCopilot?: () => void
}

const EXPORT_WIDTH = 1920
const EXPORT_HEIGHT = 1080

function ArchitectureExportBridge({
  onDownloadReady,
}: {
  onDownloadReady?: (download: (() => Promise<void>) | null) => void
}) {
  const { getNodes } = useReactFlow()
  const readyRef = useRef(onDownloadReady)
  readyRef.current = onDownloadReady

  useEffect(() => {
    const download = async () => {
      const nodes = getNodes()
      if (!nodes.length) return

      const viewportEl = document.querySelector(
        '.architecture-canvas .react-flow__viewport',
      ) as HTMLElement | null
      if (!viewportEl) return

      const bounds = getNodesBounds(nodes)
      const viewport = getViewportForBounds(
        bounds,
        EXPORT_WIDTH,
        EXPORT_HEIGHT,
        0.2,
        2,
        0.12,
      )

      const dataUrl = await toPng(viewportEl, {
        backgroundColor: '#090b10',
        width: EXPORT_WIDTH,
        height: EXPORT_HEIGHT,
        style: {
          width: `${EXPORT_WIDTH}px`,
          height: `${EXPORT_HEIGHT}px`,
          transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.zoom})`,
        },
      })

      const link = document.createElement('a')
      link.download = 'architecture-diagram.png'
      link.href = dataUrl
      link.click()
    }

    readyRef.current?.(download)
    return () => readyRef.current?.(null)
  }, [getNodes])

  return null
}

export function ArchitectureCanvas({
  graph,
  onDownloadReady,
  onSelectionChange,
  selectedFile,
  onSelectFile,
  onAskCopilot,
}: Props) {
  const initialNodes = useMemo(() => layoutNodes(graph), [graph])
  const initialEdges = useMemo(() => toFlowEdges(graph), [graph])
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const selectionChangeRef = useRef(onSelectionChange)
  selectionChangeRef.current = onSelectionChange

  useEffect(() => {
    setNodes(layoutNodes(graph))
    setEdges(toFlowEdges(graph))
    setSelectedId(null)
    setDetailOpen(false)
    selectionChangeRef.current?.(null)
  }, [graph, setNodes, setEdges])

  const selected = useMemo(
    () => graph.nodes.find((n) => n.id === selectedId) ?? null,
    [graph.nodes, selectedId],
  )

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelectedId(node.id)
      setDetailOpen(true)
      selectionChangeRef.current?.(graph.nodes.find((n) => n.id === node.id) ?? null)
    },
    [graph.nodes],
  )

  if (!graph.nodes.length) {
    return (
      <div className="architecture-empty">
        <p className="muted">No architecture nodes to display after validation.</p>
      </div>
    )
  }

  return (
    <div className={`architecture-viz${detailOpen && selected ? ' has-detail' : ''}`}>
      <div className="architecture-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick}
          onPaneClick={() => {
            setSelectedId(null)
            setDetailOpen(false)
            selectionChangeRef.current?.(null)
          }}
          fitView
          fitViewOptions={{ padding: 0.22 }}
          minZoom={0.35}
          maxZoom={1.75}
          proOptions={{ hideAttribution: true }}
          colorMode="dark"
        >
          <ArchitectureExportBridge onDownloadReady={onDownloadReady} />
          <Background gap={22} size={1} color="#1e293b" />
          <Controls showInteractive={false} />
          <MiniMap
            pannable
            zoomable
            nodeStrokeWidth={3}
            maskColor="rgba(2, 6, 12, 0.72)"
            style={{ background: '#0b1018' }}
          />
        </ReactFlow>
      </div>

      <aside className={`architecture-detail${detailOpen && selected ? ' is-open' : ''}`}>
        {selected ? (
          <>
            <div className="architecture-detail-head">
              <p className="eyebrow">{KIND_LABELS[selected.kind] ?? selected.kind}</p>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setDetailOpen(false)}>
                Close
              </button>
            </div>
            <h3>{selected.label}</h3>
            {selected.description ? <p className="muted">{selected.description}</p> : null}
            {onAskCopilot ? (
              <button type="button" className="btn btn-secondary btn-sm ask-copilot-btn" onClick={onAskCopilot}>
                Ask Copilot about {selectedFile ? 'this file' : 'this component'}
              </button>
            ) : null}
            {selected.file_paths?.length ? (
              <>
                <h4>Files</h4>
                <ul className="path-list">
                  {selected.file_paths.slice(0, 8).map((path) =>
                    onSelectFile ? (
                      <li key={path}>
                        <button
                          type="button"
                          className={`path-select${selectedFile === path ? ' is-selected' : ''}`}
                          aria-pressed={selectedFile === path}
                          onClick={() => onSelectFile(path)}
                        >
                          {path}
                        </button>
                      </li>
                    ) : (
                      <li key={path}>{path}</li>
                    ),
                  )}
                </ul>
              </>
            ) : null}
            {selected.evidence?.length ? (
              <>
                <h4>Evidence</h4>
                <ul className="path-list">
                  {selected.evidence.slice(0, 8).map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </>
            ) : null}
          </>
        ) : (
          <p className="muted">Select a component to inspect linked files and evidence.</p>
        )}
      </aside>
    </div>
  )
}
