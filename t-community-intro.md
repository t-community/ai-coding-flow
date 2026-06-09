# T-Community GitHub Organization 介紹

> GitHub Org：[https://github.com/orgs/t-community](https://github.com/orgs/t-community)

---

## 為什麼建立這個 Org？

這個 org 並非來自任何指派，而是觀察到團隊長期以來有幾個可以改善的地方，所以試著建起來，希望對大家有幫助。

**程式碼散落在個人帳號**
同事 fork 的開源專案、或自己開發的小工具，往往只存在個人 GitHub 帳號底下，其他人不知道它的存在，有時候甚至會重複開發相同的東西。

**人員異動造成技術資產流失**
當有人離職，放在個人帳號的 repo 就很難再取得，相關的知識與維護成本也難以移交。

**Container Image 難以追蹤**
各自 push 到個人 Docker Hub，要找某個服務的 image 幾乎需要靠猜測或逐一詢問。

**CI/CD 設定各自為政**
類似性質的 GitHub Actions 由每個人各自維護，重複投入時間且難以共享改善。

建立這個 org 的出發點，是希望提供一個共用的空間，讓程式碼和 image 可以集中存放、互相發現，也不會因為個別成員的異動而遺失。

---

## 哪些東西適合放進來？

以下幾種情況都適合考慮放入這個 org：

| 類型 | 說明 | 範例 |
|------|------|------|
| **Fork 的開源專案** | 有客製化、或需要持續追蹤上游更新的開源 repo | CoreDNS、Conductor |
| **內部開發的工具** | 自行開發、但其他人也可能用到的專案 | inventory-api、ai-coding-flow |
| **共用 Helm Chart** | 可重複使用的 Kubernetes 部署模板 | helm-api-service |
| **實驗性 / 探索性專案** | 評估中的技術或 PoC，方便大家一起參考試用 | gitlab-mcp |

判斷的參考點：如果這段程式碼不是純粹的個人練習，而是「將來有可能被其他人需要」，那放在 org 底下會比放在個人帳號更有價值。

---

## 現有 Repositories

### 內部開發專案

#### [`inventory-api`](https://github.com/t-community/inventory-api)
基於 **Django REST Framework** 開發的虛擬化資源管理系統後端 API（Python）。
提供多租戶環境下虛擬機、Kubernetes 叢集等資源的調度與管理介面。
支援 VS Code Dev Container，clone 後即可啟動開發環境。

#### [`inventory-ui`](https://github.com/t-community/inventory-ui)
對應 inventory-api 的 **React 前端**（TypeScript），內部稱為 **VirtFlow**。
提供儀表板、實體基礎設施管理、VM 管理、K8s 叢集管理等介面。

#### [`ai-coding-flow`](https://github.com/t-community/ai-coding-flow)
**自主 AI 開發工作流**。監聽 GitHub / GitLab 上的 Issue，由 AI 自動撰寫程式、執行測試、開 PR/MR 並留下 Code Review 意見，全程不需人工介入，只需最後決定是否 merge。
同時支援 GitHub 與自建 GitLab，也可搭配本地 LLM（Ollama 等）離線運作。

---

### Helm Chart

#### [`helm-api-service`](https://github.com/t-community/helm-api-service)
Production-ready 的**通用 API Service Helm Chart**，可快速將容器化的後端服務部署至 Kubernetes 叢集，減少各專案重複撰寫 Helm Chart 的成本。

---

### Fork 的開源專案（客製化維護）

#### [`coredns`](https://github.com/t-community/coredns)
**CoreDNS** 的 fork — 以 Plugin 串接方式運作的 DNS Server，以 Go 撰寫。
若需要客製化 DNS 解析邏輯，可在此 fork 上進行修改，同時保有追蹤上游更新的能力。

#### [`nftables-exporter`](https://github.com/t-community/nftables-exporter)
**nftables Prometheus Exporter** 的 fork（Go）。
將 nftables 的統計指標匯出至 Prometheus，供監控平台使用。

#### [`galaxy-operator`](https://github.com/t-community/galaxy-operator)
**Ansible Galaxy Operator** 的 fork，以 Ansible Operator SDK 實作的 Kubernetes Operator，用於在 K8s 上部署與管理 Ansible Galaxy NG（私有 Ansible Role / Collection 倉庫）。

#### [`conductor`](https://github.com/t-community/conductor)
**Conductor OSS** 的 fork — 事件驅動的 Agentic Workflow Engine（Java），具備高可靠性與擴展性，適合作為 AI Agent 或複雜業務流程的執行引擎。

---

### MCP Server

#### [`gitlab-mcp`](https://github.com/t-community/gitlab-mcp)
**GitLab MCP Server**（TypeScript）。
讓 AI 客戶端（Claude、Cursor、VS Code Copilot 等）透過 MCP 協議操作 GitLab，支援 Project、MR、Issue、Pipeline、Wiki 等功能，同時支援 PAT / OAuth 及 Self-hosted GitLab。

---

### Org 設定

#### [`.github`](https://github.com/t-community/.github)
存放 Org 層級的 GitHub 設定，包含 Org Profile、共用 Issue / PR 範本、共用 GitHub Actions Workflow 等。

---

## Container Image 管理：GHCR

除了程式碼之外，image 的管理也是這次想一併改善的部分。目前大家各自 push 到個人 Docker Hub，可以考慮改用 GitHub 提供的 **GitHub Container Registry（ghcr.io）**。

### 為什麼值得考慮？

| | Docker Hub（目前） | GHCR |
|---|---|---|
| 費用 | 超過限制需付費 | **免費**（Public image 無上限） |
| 歸屬 | 散落在個人帳號 | 統一屬於 `t-community` org |
| 可見性 | 各自管理，不易發現 | 集中在 org 下，一目了然 |
| 存取控制 | 帳號各自設定 | 與 GitHub repo 權限整合 |

### Image 命名慣例

```
ghcr.io/t-community/<repo-name>:<tag>
```

範例：

```
ghcr.io/t-community/inventory-api:latest
ghcr.io/t-community/inventory-api:v1.2.0
ghcr.io/t-community/ai-coding-flow:main
```

### 如何在 GitHub Actions 中 Push Image

```yaml
- name: Log in to GHCR
  uses: docker/login-action@v3
  with:
    registry: ghcr.io
    username: ${{ github.actor }}
    password: ${{ secrets.GITHUB_TOKEN }}

- name: Build and push
  uses: docker/build-push-action@v5
  with:
    push: true
    tags: ghcr.io/t-community/<your-repo>:${{ github.sha }}
```

> `GITHUB_TOKEN` 是 Actions 自動提供的，不需要額外設定 Secret。

---

## 如何開始使用

### 1. 加入 Org

聯絡 Org Owner，以 GitHub 帳號申請加入 `t-community` organization 即可。

### 2. 將既有的 Repo 移入

若個人帳號下有公司在使用的 repo，可以考慮移入 org，有兩種方式：

- **Transfer**：直接將 repo 轉移至 org，commit 歷史與 star 均會保留，一般建議優先採用
- **Fork**：在 org 下建立 fork，適合仍需追蹤上游更新的開源專案

### 3. 在 Org 下建立新 Repo

流程與平時相同，選擇在 `t-community` 底下建立即可。建議附上 Description 與基本 README，方便其他人了解用途。

### 4. 使用共用 CI/CD

`.github` repo 中有可重用的 Workflow，若新 repo 的 CI/CD 需求類似，可直接引用，不需要從頭撰寫。

---

## 一些建議（供參考，不是規定）

- Repo 名稱建議使用小寫 kebab-case（如 `my-service`），比較容易辨識與統一
- 盡量附上 README，簡短說明用途與啟動方式即可
- Fork 自開源的 repo，建議在 README 中說明與上游的差異，方便日後維護
- Image 若有機會，可以考慮改為 push 至 GHCR，讓大家更容易找到
- 若不確定是否需要開新 repo，或擔心與現有專案重疊，歡迎先提出討論

---

> 這個 org 是開放給大家共用的空間，有任何想法或問題，歡迎直接開 Issue 或在 org 的討論區留言。
