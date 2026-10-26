import { QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router';
import Blocklist from 'Activity/Blocklist/Blocklist';
import History from 'Activity/History/History';
import Queue from 'Activity/Queue/Queue';
import ErrorBoundary from 'Components/ErrorBoundary';
import Link from 'Components/Link/Link';
import { Alert } from 'Components/Misc';
import Page from 'Components/Page/Page';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import Tasks from 'System/Tasks/Tasks';
import { urlBase } from 'Utilities/api';
import Missing from 'Wanted/Missing/Missing';
import BookSearch from 'Wanted/Search/BookSearch';
import queryClient from './queryClient';

function NotFound() {
  return (
    <PageContent title="Not Found">
      <PageContentBody>
        <Alert kind="warning">
          There's no page here. <Link to="/home">Go to the library</Link>
        </Alert>
      </PageContentBody>
    </PageContent>
  );
}

function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter basename={urlBase() || '/'}>
          <Page>
            <Routes>
              <Route path="/activity" element={<Navigate to="/activity/queue" replace={true} />} />
              <Route path="/activity/queue" element={<Queue />} />
              <Route path="/activity/history" element={<History />} />
              <Route path="/activity/blocklist" element={<Blocklist />} />
              <Route path="/wanted" element={<Navigate to="/wanted/missing" replace={true} />} />
              <Route path="/wanted/missing" element={<Missing />} />
              <Route path="/wanted/search" element={<BookSearch />} />
              <Route path="/system" element={<Navigate to="/system/tasks" replace={true} />} />
              <Route path="/system/tasks" element={<Tasks />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </Page>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

export default App;
