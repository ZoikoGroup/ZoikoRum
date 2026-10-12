
interface Profile {
  id: string
  name: string
  hourlyRate: number
  matchScore: number
  matchReason?: string
  skills: string[]
}

export function CompareProfiles({ profiles, onClose }: { profiles: Profile[], onClose: () => void }) {
  if (profiles.length < 2) return null

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center p-8 z-50 overflow-y-auto">
      <div className="bg-white rounded-xl p-6 max-w-5xl w-full">
        <div className="flex justify-between items-center mb-6">
          <h2 className="text-2xl font-bold">Compare Professionals</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-black font-bold text-xl">&times;</button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {profiles.map(p => (
            <div key={p.id} className="border rounded-lg p-4 shadow-sm flex flex-col">
              <h3 className="text-xl font-semibold mb-2">{p.name}</h3>
              <div className="text-sm text-green-700 bg-green-50 p-2 rounded mb-4">
                <strong>{p.matchScore}% Match</strong>
                {p.matchReason && <p className="mt-1 italic">{p.matchReason}</p>}
              </div>
              <ul className="space-y-2 mb-4 flex-grow">
                <li><strong>Rate:</strong> ${p.hourlyRate}/hr</li>
                <li><strong>Skills:</strong> {p.skills.join(', ')}</li>
              </ul>
              <button className="mt-auto w-full py-2 bg-blue-600 text-white rounded hover:bg-blue-700">Invite to Pitch</button>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
