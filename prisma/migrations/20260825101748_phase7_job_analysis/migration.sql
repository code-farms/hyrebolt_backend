-- CreateTable
CREATE TABLE "JobAnalysis" (
    "id" TEXT NOT NULL,
    "jobId" TEXT NOT NULL,
    "analysis" JSONB NOT NULL,
    "confidence" DOUBLE PRECISION,
    "model" TEXT NOT NULL,
    "promptVersion" TEXT NOT NULL,
    "inputTokens" INTEGER,
    "outputTokens" INTEGER,
    "processedAt" TIMESTAMP(3) NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "JobAnalysis_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "JobAnalysis_jobId_key" ON "JobAnalysis"("jobId");

-- CreateIndex
CREATE INDEX "JobAnalysis_promptVersion_idx" ON "JobAnalysis"("promptVersion");

-- AddForeignKey
ALTER TABLE "JobAnalysis" ADD CONSTRAINT "JobAnalysis_jobId_fkey" FOREIGN KEY ("jobId") REFERENCES "Job"("id") ON DELETE CASCADE ON UPDATE CASCADE;
