-- CreateEnum
CREATE TYPE "PreferenceSignalKind" AS ENUM ('LIKE', 'DISLIKE', 'SAVE', 'APPLY', 'NOT_RELEVANT', 'HIDE_COMPANY', 'HIDE_ROLE');

-- CreateTable
CREATE TABLE "UserPreferenceSignal" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "jobId" TEXT,
    "kind" "PreferenceSignalKind" NOT NULL,
    "weight" DOUBLE PRECISION NOT NULL DEFAULT 1,
    "roleKey" TEXT NOT NULL,
    "roleLabel" TEXT NOT NULL,
    "companyId" TEXT,
    "companyKey" TEXT NOT NULL,
    "companyLabel" TEXT NOT NULL,
    "locationKey" TEXT,
    "workMode" TEXT,
    "skills" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "UserPreferenceSignal_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "UserPreferenceSignal_userId_kind_idx" ON "UserPreferenceSignal"("userId", "kind");

-- CreateIndex
CREATE INDEX "UserPreferenceSignal_jobId_idx" ON "UserPreferenceSignal"("jobId");

-- CreateIndex
CREATE UNIQUE INDEX "UserPreferenceSignal_userId_jobId_kind_key" ON "UserPreferenceSignal"("userId", "jobId", "kind");

-- AddForeignKey
ALTER TABLE "UserPreferenceSignal" ADD CONSTRAINT "UserPreferenceSignal_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "UserPreferenceSignal" ADD CONSTRAINT "UserPreferenceSignal_jobId_fkey" FOREIGN KEY ("jobId") REFERENCES "Job"("id") ON DELETE SET NULL ON UPDATE CASCADE;

