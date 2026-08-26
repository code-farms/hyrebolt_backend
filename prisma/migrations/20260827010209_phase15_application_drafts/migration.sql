-- CreateEnum
CREATE TYPE "ApplicationDraftKind" AS ENUM ('COVER_LETTER', 'RECRUITER_MESSAGE', 'RESUME_TAILORING', 'APPLICATION_NOTES');

-- CreateTable
CREATE TABLE "ApplicationDraft" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "jobId" TEXT NOT NULL,
    "kind" "ApplicationDraftKind" NOT NULL,
    "content" TEXT NOT NULL,
    "generatedContent" TEXT,
    "resumeVersionId" TEXT,
    "promptVersion" TEXT,
    "model" TEXT,
    "generatedAt" TIMESTAMP(3),
    "editedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "ApplicationDraft_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "ApplicationDraft_jobId_idx" ON "ApplicationDraft"("jobId");

-- CreateIndex
CREATE UNIQUE INDEX "ApplicationDraft_userId_jobId_kind_key" ON "ApplicationDraft"("userId", "jobId", "kind");

-- AddForeignKey
ALTER TABLE "ApplicationDraft" ADD CONSTRAINT "ApplicationDraft_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ApplicationDraft" ADD CONSTRAINT "ApplicationDraft_jobId_fkey" FOREIGN KEY ("jobId") REFERENCES "Job"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ApplicationDraft" ADD CONSTRAINT "ApplicationDraft_resumeVersionId_fkey" FOREIGN KEY ("resumeVersionId") REFERENCES "ResumeVersion"("id") ON DELETE SET NULL ON UPDATE CASCADE;

