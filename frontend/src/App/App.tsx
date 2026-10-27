import { QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router';
import Blocklist from 'Activity/Blocklist/Blocklist';
import History from 'Activity/History/History';
import Queue from 'Activity/Queue/Queue';
import AddNew from 'AddNew/AddNew';
import AuthorDetails from 'Author/Details/AuthorDetails';
import AuthorIndex from 'Author/Index/AuthorIndex';
import ErrorBoundary from 'Components/ErrorBoundary';
import Link from 'Components/Link/Link';
import { Alert } from 'Components/Misc';
import Page from 'Components/Page/Page';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import Backups from 'System/Backup/Backups';
import Events from 'System/Events/Events';
import LogFiles from 'System/LogFiles/LogFiles';
import Status from 'System/Status/Status';
import Tasks from 'System/Tasks/Tasks';
import Updates from 'System/Updates/Updates';
import { urlBase } from 'Utilities/api';
import Connect from 'Settings/Connect/Connect';
import Profiles from 'Settings/Profiles/Profiles';
import CutoffUnmet from 'Wanted/CutoffUnmet/CutoffUnmet';
import Missing from 'Wanted/Missing/Missing';
import BookSearch from 'Wanted/Search/BookSearch';
import queryClient from './queryClient';
import { useServerEvents } from './serverEvents';

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
  useServerEvents();

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
              <Route path="/wanted/cutoffunmet" element={<CutoffUnmet />} />
              <Route path="/settings" element={<Navigate to="/settings/profiles" replace={true} />} />
              <Route path="/settings/profiles" element={<Profiles />} />
              <Route path="/settings/connect" element={<Connect />} />
              <Route path="/add" element={<Navigate to="/add/new" replace={true} />} />
              <Route path="/add/new" element={<AddNew />} />
              <Route path="/authors" element={<AuthorIndex />} />
              <Route path="/author/:authorId" element={<AuthorDetails />} />
              <Route path="/system" element={<Navigate to="/system/status" replace={true} />} />
              <Route path="/system/status" element={<Status />} />
              <Route path="/system/tasks" element={<Tasks />} />
              <Route path="/system/backup" element={<Backups />} />
              <Route path="/system/updates" element={<Updates />} />
              <Route path="/system/events" element={<Events />} />
              <Route path="/system/logs/files" element={<LogFiles />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </Page>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

export default App;
