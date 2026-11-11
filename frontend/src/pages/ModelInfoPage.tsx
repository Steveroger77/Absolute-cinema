import { useQuery } from "@tanstack/react-query";
import { AppShell } from "../components/AppShell";
import { api } from "../lib/api";

interface MetricSlice {
  rmse: number;
  mae: number;
  precision_at_10: number;
  recall_at_10: number;
  catalogue_coverage_at_10: number;
  popularity_bias_mean_log_pop: number;
}

export function ModelInfoPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["model-info"],
    queryFn: api.getModelInfo,
  });

  const metricsObj = (data?.metrics as Record<string, unknown>) || {};
  const dataset = (metricsObj.dataset as Record<string, unknown>) || {};
  const evalMetrics = (metricsObj.metrics as Record<string, Record<string, MetricSlice>>) || {};

  return (
    <AppShell>
      <div className="cinema-container pt-6 pb-12 flex flex-col gap-8">
        <div className="pb-6 border-b" style={{ borderColor: "var(--color-rule)" }}>
          <h1 style={{ fontSize: "var(--text-display)" }}>Recommendation Engine</h1>
          <p className="text-sm mt-2" style={{ color: "var(--color-ink-muted)" }}>
            Sparse CSR Collaborative Filtering (Item-CF + User-CF hybrid) with TF-IDF content
            fallback and Bayesian popularity cold start.
          </p>
        </div>

        {isLoading ? (
          <div className="skeleton-block h-64 w-full" />
        ) : (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div
                className="p-4 rounded-2xl border"
                style={{
                  backgroundColor: "var(--color-paper-2)",
                  borderColor: "var(--color-rule)",
                }}
              >
                <div className="text-xs" style={{ color: "var(--color-ink-subtle)" }}>
                  Model version
                </div>
                <div
                  className="tabular-figure text-2xl font-semibold mt-1"
                  style={{ color: "var(--color-accent)" }}
                >
                  {data?.version || "v1"}
                </div>
              </div>
              <div
                className="p-4 rounded-2xl border"
                style={{
                  backgroundColor: "var(--color-paper-2)",
                  borderColor: "var(--color-rule)",
                }}
              >
                <div className="text-xs" style={{ color: "var(--color-ink-subtle)" }}>
                  Catalogue size
                </div>
                <div className="tabular-figure text-2xl font-semibold mt-1">
                  {String(dataset.total_movies ?? 2300)}
                </div>
              </div>
              <div
                className="p-4 rounded-2xl border"
                style={{
                  backgroundColor: "var(--color-paper-2)",
                  borderColor: "var(--color-rule)",
                }}
              >
                <div className="text-xs" style={{ color: "var(--color-ink-subtle)" }}>
                  MovieLens ratings
                </div>
                <div className="tabular-figure text-2xl font-semibold mt-1">
                  {String(dataset.movielens_ratings ?? "—")}
                </div>
              </div>
              <div
                className="p-4 rounded-2xl border"
                style={{
                  backgroundColor: "var(--color-paper-2)",
                  borderColor: "var(--color-rule)",
                }}
              >
                <div className="text-xs" style={{ color: "var(--color-ink-subtle)" }}>
                  Synthetic Indian ratings
                </div>
                <div className="tabular-figure text-2xl font-semibold mt-1">
                  {String(dataset.synthetic_ratings ?? "—")}
                </div>
              </div>
            </div>

            {(["movielens", "all"] as const).map((splitKey) => {
              const group = evalMetrics[splitKey];
              if (!group) return null;
              return (
                <section key={splitKey}>
                  <h2 style={{ fontSize: "1.4rem" }} className="mb-3 capitalize">
                    {splitKey === "movielens"
                      ? "MovieLens real ratings holdout"
                      : "Combined dataset holdout"}
                  </h2>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left border-collapse text-sm">
                      <thead>
                        <tr
                          className="border-b"
                          style={{
                            borderColor: "var(--color-rule-strong)",
                            color: "var(--color-ink-muted)",
                          }}
                        >
                          <th className="py-2.5 pr-4 font-medium">Model</th>
                          <th className="py-2.5 px-4 font-medium">RMSE</th>
                          <th className="py-2.5 px-4 font-medium">MAE</th>
                          <th className="py-2.5 px-4 font-medium">Precision@10</th>
                          <th className="py-2.5 px-4 font-medium">Recall@10</th>
                          <th className="py-2.5 pl-4 font-medium">Coverage@10</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(group).map(([name, m]) => (
                          <tr
                            key={name}
                            className="border-b"
                            style={{ borderColor: "var(--color-rule)" }}
                          >
                            <td className="py-2.5 pr-4 font-medium">{name}</td>
                            <td className="py-2.5 px-4 tabular-figure">{m.rmse}</td>
                            <td className="py-2.5 px-4 tabular-figure">{m.mae}</td>
                            <td className="py-2.5 px-4 tabular-figure">{m.precision_at_10}</td>
                            <td className="py-2.5 px-4 tabular-figure">{m.recall_at_10}</td>
                            <td className="py-2.5 pl-4 tabular-figure">
                              {(m.catalogue_coverage_at_10 * 100).toFixed(1)}%
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              );
            })}

            {typeof dataset.synthetic_disclosure === "string" && (
              <div
                className="p-4 rounded-2xl border text-sm"
                style={{
                  backgroundColor: "var(--color-paper-2)",
                  borderColor: "var(--color-rule)",
                  color: "var(--color-ink-muted)",
                }}
              >
                {dataset.synthetic_disclosure}
              </div>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}
